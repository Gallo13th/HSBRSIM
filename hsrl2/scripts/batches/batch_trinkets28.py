"""批次 trinkets28 — 饰品第二十八批（作业单 2026-09-14，18 张）。

台账来源: 派发作业单给定的 18 个 id（`docs/agents/TRINKET_LEDGER.md` 片
2/3 的并集）。18/18 在 `CardDB` 存在、18/18 在
`CardDB.trinket_offer_pool()` 中（运行核验——商店可提供成员），且在本批
之前**全部**不在 `REGISTRY`（与既有 batch_trinkets1..27 注册集合互不
相交；其中 868/869/944/971/987/994/179/274/283/300/350/366/417/419/
803/804/806/809 曾在 batch_trinkets12/13/14/15/24/25 的 DEFERRED 台账
中留档，本轮按 2026-09-02 新落地原语逐张复评）。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码；文本字面量按
SOP §3 在各类 `Params:` 行显式声明）；关联卡一律走数据链
`CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6）；随机一律
`game.rng`；状态写在 hero 作用域 tag / source 实体属性（无 game 级
flag——SOP §12 item 9）。

**本轮新引擎原语复核**（作业单列出的"已被解锁"清单，逐张实测后裁决）
═══════════════════════════════════════════════════════════════════════
  - `gold_gained(hero=, amount=)`（`hsrl2/hero.py` `Hero.gold` setter
    广播，覆盖回合收入 / 售卖 / `GainGold` / 脚本直改——上限 99 截断后
    的**实际增量**才是 amount）→ **解冻 `BG32_MagicItem_350` Splinter of
    Aurum**（"When you have {1} Gold, get a random Golden Tier 5 minion.
    (Once per game.)"）。旧台账（batch_trinkets14/24）"引擎无金币增加
    观察点"已过期——`hsrl2/tests/test_engine_primitives.py::
    TestGoldGainedObservation` 是生产点回归。
  - `GameTag.TAVERN_OFFER_TIER_EXACT`（`hsrl2/tags.py`；`refresh_tavern`
    读取点 `hsrl2/game.py` L442——本次刷新的**全部**随从位取自恰好该档）
    → **解冻 `BG32_MagicItem_366` Guiding Candle**（"Your first two
    Refreshes each turn contain only Tier 6 cards."）。`tavern_refresh`
    携带 `auto=`（L512）区分"你主动刷新"与引擎自动刷新（RULES §7.4.9 /
    Frigid Blossom 口径）——自动刷新不计入、不消耗、也不被本效果改写。
  - **战斗内 `Transform` 持久化**（`hsrl2/actions/stats.py` +
    `Game._combat_transforms` 战后重放，提交 5cc6666; RULES §3.5 例外 /
    §6.21）→ **解冻 `BG32_MagicItem_419` Yu'lon Sticker**（"Start of
    Combat: Make your highest-Tier Dragon Golden."——金色化是永久卡身份
    变更，旧实现被 `hero.board = list(board_before)` 回滚）。
  - `GameTag.TAVERN_EXTRA_TIER_SLOTS` + `TAVERN_EXTRA_TIER` /
    `MINIONS_SOLD_THIS_TURN` / `spell_resolved` vs `spell_resolving` /
    `trigger_deathrattle` / `grant_combat_deathrattle` /
    `destroy_minion`+`minion_destroyed` / `add_tier_aura` /
    `add_permanent_spellcraft_rule` / `add_tavern_entity`+
    `tavern_entity_added`+`tavern_refresh_complete` / `cast_spell_effect` /
    `grant_card_copy_to_hand`（满手入队 = 成功） /
    `run_combat` 恢复 `_magnetic_stack` / `racefx.elemental_give_bonus` /
    `COUNTER_ELEMENTALS_PLAYED`+`elemental_played` / `_pair_gifts(turn=)`
    逐个核对: **均不解锁本批其余 15 张**（逐条理由见各 DEFERRED 类
    docstring）。并行批 `batch_payload_minions`（工作区）已注册本批
    944/971/274/803/804 的关联卡**本体**——但本卡效果依赖的
    "also/extra" **修饰语消费点**仍不在那些脚本内，且本批不可写他批次
    脚本（SOP §12 item 2/14）→ 274 已由 batch_trinkets34、803 已由
    batch_trinkets36、804 已由 batch_trinkets35 注册并迁出，944/971
    维持 DEFERRED（依赖描述已按新状态更新，见各类 docstring）。
  - 结论: 新原语恰好解锁 **3 张**（350 / 366 / 419）；其余 15 张维持
    DEFERRED（SOP §6b 二态铁律——**不注册**，禁止第三态）。

注册 3 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG32_MagicItem_350 Splinter of Aurum (Lesser, school=11) —
      `on_bind` 注册 `gold_gained` 持久监听（owner=饰品; owner 过滤
      `hero is 本人`）: `hero.gold >= num(1)`（=15）时从**恰好 Tier 5**
      的池剩余随从中 `game.rng.choice` 取一张，经
      `game.grant_card_copy_to_hand(hero, def, golden=True)` 交付金色
      独立卡定义副本（`GILDED_NOT_TRIPLED` 池配平、满手入等待队列
      RULES §3.3）。`(Once per game.)` 记在 source 实体
      （`source._splinter_used`）; **池空 → 本轮落空且不消耗 once**
      （Primordial Terrarium/Funeral Wreath 口径——落空不扣额度）。

  BG32_MagicItem_366 Guiding Candle (Greater, school=12) —
      `on_bind` 武装 `GameTag.TAVERN_OFFER_TIER_EXACT=6`（hero 级）并注册
      `tavern_refresh` 持久监听: **主动刷新**（`auto is False`）消耗一次
      充能，充能耗尽即 `hero.clear(TAVERN_OFFER_TIER_EXACT)` 恢复常规
      档位; **自动刷新**（`auto is True`）不计入、不消耗，只在刷新后
      重新武装（保证下一次主动刷新仍被覆盖）。`start_of_turn` 在回合
      开始的**自动刷新之前**把充能重置为 `num(0)`×副本数并解除武装
      （`_begin_recruit_for` 顺序: SoT 钩子 → `refresh_tavern(auto=True)`
      ——若不在 SoT 解除武装，回合开始的自动刷新会被误变成"只出 T6"）。
      副本条款: 每份副本各 `+num(0)` 充能（协调者单监听，多副本**叠加**
      ——wiki 32.2.1 hotfix "Guiding Candle now stacks correctly"）。

  BG32_MagicItem_419 Yu'lon Sticker (Lesser, school=11) —
      `start_of_combat`: 本人棋盘存活、`race ∈ {DRAGON, ALL}`、非金色、
      `golden_version` 存在的最高 `tech_level` 龙（并列取最左）经
      `batch_battlecry._goldenize` 金色化（`Transform` 到金色独立卡定义
      + `GILDED_NOT_TRIPLED` 池配平 + 不发三连奖励）。引擎
      `_combat_transforms` 战后原位重放 → **金色化跨战斗持久**（RULES
      §3.5 例外）。空候选 → 落空。

DEFERRED 15 张 → **13 张**（**不注册**；Status / Dependency / Implementation
path 逐张见各类 docstring，禁止第三态——SOP §6b）。
**2026-09-21 迁出 2 张**: 971 Enforcer / 179 Drakkari Portrait 由
`batch_family_races` 注册（RACES 家族类型身份改写）。
═══════════════════════════════════════════════════════════════════════
  A. 载荷"修饰语"消费点缺失（关联卡**本体**已由并行批
     `batch_payload_minions` 注册，但其出口不读 hero 级修饰标记 /
     本批不可写他批次脚本——RULES §7.4.6 例外条 + SOP §12 item 2/14）
     - BG30_MagicItem_869 Felblood Portrait（BG29_873/BG29_877 仍未注册）
     - BG30_MagicItem_944 Redeemer Portrait（Nalaa 已注册，无 extra 通道）
     - BG30_MagicItem_971 Enforcer Portrait（Lightfang 已注册，缺
       "追加全类型身份"协议 + RACES）
     - BG32_MagicItem_274 Bristlebach Portrait（**已迁出 batch_trinkets34**; 此前
       无 target-scope 通道）
     - BG32_MagicItem_803 Macaw Portrait（**已迁出 batch_trinkets36**;
       此前无 extra-battlecry 通道 + "最左战吼"选定口径未定——
       现由 RULES §7.4.17 条件化战吼 + 32.2 论坛复现串裁定）
     - BG32_MagicItem_804 Selfless Portrait（**已迁出 batch_trinkets35**;
       此前读法未定 + 需"条件化战吼"协议——直挂钩子会让无饰品时误吃
       `bc_first` 配额/误入战吼目标集）
     - BG32_MagicItem_806 Battlecruiser Portrait（BG31_HERO_801pt +
       Upgrade 子系统）
  B. 家族级"给予者加成"通道 + 增量权威（读取方在他批次脚本，本批不可写
     ——SOP §12 item 2/14 + §16b item 32）
     - BG30_MagicItem_868 Rewinder Portrait（第二关联卡 + Attack 增量无权威）
     - BG30_MagicItem_987 Balladist Portrait（`{0}` Attack 字段为 None）
     - BG32_MagicItem_283 Czarina Portrait（Health 增量无字段）
  C. 引擎缺口（原语缺失; ENGINE_BACKLOG 同条目）
     - BG32_MagicItem_179 Drakkari Portrait（多值种族 `RACES`）
     - BG32_MagicItem_417 Tarecgosa Sticker（Bonus Keyword 定义域 +
       位置/种族 PERSIST 光环）
     - BG30_MagicItem_994 Yogg-Tastic Pastry（Wheel of Yogg-Saron）
     - BG32_MagicItem_300 Putricide Sticker（Craft 多步合成链）
  D. 语义无权威（SOP §6b 第 4 步；本轮复读信源无新证据）
     - BG32_MagicItem_809 Gem Donation（"plays its Blood Gems" 三种读法）

关联卡台账（RULES §7.4.6——"Get a X" 交付正确即 CORRECT；被交付卡
自身脚本未迁移只登记、不阻塞，除非本卡效果**依赖**其行为）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链 `evolution_card_id` → `db.by_dbf`） | 脚本状态 |
  |------|--------------------------------------------------|-----------|
  | BG30_MagicItem_868 | 100949 → BG26_174 Soul Rewinder（池 T2）| 已注册 |
  |                    | （+ 文本点名的 Wrath Weaver 无数据链）      |         |
  | BG30_MagicItem_869 | 109418 → BG29_873 Slimy Felblood（非池 T3）| **未注册** |
  | BG30_MagicItem_944 | 104468 → BG28_551 Nalaa the Redeemer（非池）| 已注册（并行批）|
  | BG30_MagicItem_971 | 59707 → BGS_009 Lightfang Enforcer（非池）| 已注册（并行批）|
  | BG30_MagicItem_987 | 99011 → BG26_814 Lovesick Balladist（池 T4）| 已注册 |
  | BG32_MagicItem_179 | 101314 → BG26_ICC_901 Drakkari Enchanter（池 T5）| 已注册 |
  | BG32_MagicItem_274 | 100997 → BG26_157 Bristlebach（非池 T6）| 已注册（batch_trinkets34 迁本卡）|
  | BG32_MagicItem_283 | 110321 → BG28_741 Charging Czarina（池 T5）| 已注册 |
  | BG32_MagicItem_803 | 62230 → BGS_078 Monstrous Macaw（非池 T4）| 已注册（batch_trinkets36）|
  | BG32_MagicItem_804 | 96769 → BG_OG_221 Selfless Hero（非池 T2）| 已注册（batch_trinkets35）|
  | BG32_MagicItem_806 | 118684 → BG31_HERO_801pt Battlecruiser（token）| **未注册** |
  "已注册（并行批）"= `hsrl2/scripts/batches/batch_payload_minions.py`
  （工作区，2026-09-11）——本体可交付，但本批饰品效果的"also/extra"
  修饰语消费点仍缺失（见各 DEFERRED docstring）。
  说明: BG30_MagicItem_994 / BG32_MagicItem_300 / _350 / _366 / _417 /
  _419 / _809 的 `evolution_card_id` 为空（无关联卡，36.2.2 逐条核实），
  其效果完全由本体表达; _350 / _366 / _419 本批 CORRECT。

接线审计读取点（W1/W2/W3 核对）
═══════════════════════════════════════════════════════════════════════
  - W1: 饰品仅分发 `on_bind` / `start_of_turn` / `end_of_turn` /
    `start_of_combat`（本批用前三者: 350/366 = on_bind+SoT，
    419 = SoC）。15 张 DEFERRED 类**无任何钩子方法**（仅 docstring
    台账），不产生死钩子。
  - W2: 监听事件均有真实生产点——`gold_gained`
    （`Hero.gold` setter, `hsrl2/hero.py`）、`tavern_refresh`
    （`Game.refresh_tavern`, `hsrl2/game.py` L512）。
  - W3: 不写 `game._x` / `hero._x` 私有标记; 唯一 hero 级状态是引擎
    tag `TAVERN_OFFER_TIER_EXACT`（读取点 `refresh_tavern` L442）。
    其余状态落在 source 实体（`source._splinter_used` /
    `source._candle_left`）——本类自读，且不被 W3 扫描（只扫
    game/hero 前缀）。
  - 数值纪律: 350 的 `{1}`=`num(1)`=15、366 的 `{0}`=`num(0)`=2 均走
    `CardDef.num`; 文本字面量只有 350 的 "Tier 5"（`_SPLINTER_TIER`）
    与 366 的 "Tier 6"（`_CANDLE_TIER`），已在各类 `Params:` 声明。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import TAVERN_REFRESH, Listener
from hsrl2.game import GameStateError
from hsrl2.tags import GameTag, Race

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
REWINDER_PORTRAIT = "BG30_MagicItem_868"
FELBLOOD_PORTRAIT = "BG30_MagicItem_869"
REDEEMER_PORTRAIT = "BG30_MagicItem_944"
ENFORCER_PORTRAIT = "BG30_MagicItem_971"
BALLADIST_PORTRAIT = "BG30_MagicItem_987"
YOGG_TASTIC_PASTRY = "BG30_MagicItem_994"
DRAKKARI_PORTRAIT = "BG32_MagicItem_179"
BRISTLEBACH_PORTRAIT = "BG32_MagicItem_274"
CZARINA_PORTRAIT = "BG32_MagicItem_283"
PUTRICIDE_STICKER = "BG32_MagicItem_300"
SPLINTER_OF_AURUM = "BG32_MagicItem_350"
GUIDING_CANDLE = "BG32_MagicItem_366"
TARECGOSA_STICKER = "BG32_MagicItem_417"
YULON_STICKER = "BG32_MagicItem_419"
MACAW_PORTRAIT = "BG32_MagicItem_803"
SELFLESS_PORTRAIT = "BG32_MagicItem_804"
BATTLECRUISER_PORTRAIT = "BG32_MagicItem_806"
GEM_DONATION = "BG32_MagicItem_809"

# ── 文本字面量（CardDef 无模板参数且文本无占位符 —— SOP §3 允许，
#    逐值在各类 `Params:` 行声明，禁止静默漂移） ──
_SPLINTER_TIER = 5        # "get a random Golden **Tier 5** minion"
_CANDLE_TIER = 6          # "contain only **Tier 6** cards"

# Amalgam 规则: ALL 型随从对每个种族查询都合格（RULES §6.18/§8）
_DRAGON_RACES = (Race.DRAGON, Race.ALL)

# `gold_gained` 观察点（`Hero.gold` setter 广播; events.py 无同名常量——
# 与 `game.events.fire(game, "gold_gained", ...)` 字面量一致）
_GOLD_GAINED = "gold_gained"


def _hero(ctx):
    """on_bind ctx → 饰品持有英雄（引擎 grant_trinket 传 ctx={"hero": h}）。"""
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef 模板参数（缺失 → fail-loud，SOP §3）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


# ══════════════ BG32_MagicItem_350 Splinter of Aurum ══════════════


class SplinterOfAurumScript:
    """
    Natural language: [x]When you have {1} Gold, get a random Golden Tier 5
    minion. <i>(Once per game.)</i>

    Evidence: hearthstone.wiki.gg/Battlegrounds/Splinter_of_Aurum — Patch
      32.2.2（2025-05-16）"Splinter of Aurum is now correctly triggered
      when the right amount of gold is reached."（触发点是**达到该金币
      数**的时刻 → 金币增加观察点）; Wiki tags 无 [Targeted]/[Random]
      限定，文本 "a random Golden Tier 5 minion" = `game.rng` 随机取。
      已被证伪的候选读法（**未采用**）: "绑定瞬间若已 ≥{1} 金即触发"
      ——与 "when the right amount of gold is **reached**" 的官方修正
      说明不符（绑定前获得的金币不算"达到"），且无任何 Notes 支持。

    Formal spec:
      1. on_bind: 记 `source._splinter_used = False`
         （`(Once per game.)` 记在**本副本实体**上——两份副本各有一次），
         注册 `gold_gained(hero=, amount=)` 持久监听（owner=饰品;
         condition `hero is 本人`——owner 隔离，对手收入不触发）。
      2. 触发（每次金币**增加**、含回合收入 / 售卖 / `GainGold` /
         脚本直改——`Hero.gold` setter 是唯一入口，上限 99 截断后的
         实际增量才广播）: 若 `hero.gold >= num(1)`（=15）且本副本未用
         过，则执行交付。
      3. 交付: 候选 = `_pool_candidates(game, min_tier=5, max_tier=5)`
         （**恰好 Tier 5** 的池剩余随从; 池中无副本者排除，RULES
         §2.4）→ `game.rng.choice` → `game.grant_card_copy_to_hand(
         hero, def, golden=True)`:
           - 金色 = **独立卡定义**（`create_minion(golden=True)`），
             非"数值×2"近似;
           - 占池 1 份基础副本并打 `GILDED_NOT_TRIPLED`
             （RULES §2.3 非三连金口径: 出售/淘汰回池 1 份而非 3 份）;
           - 白板副本（无附魔）、满手 → 等待队列（RULES §3.3）。
      4. **落空不消耗额度**: 池中无任何 Tier 5 副本 → 本次不交付、
         `_splinter_used` 保持 False（下次满足条件仍可触发）——
         与 Primordial Terrarium / Funeral Wreath 的"落空不扣额度"
         口径一致。
      5. 触发后置 `_splinter_used = True`（在交付**之前**置位，防同一
         次 `gold_gained` 的嵌套收入重复交付）。
      6. 只作用于本人: 对手获得金币不触发本人（owner 隔离）; 对手
         `_splinter_used` 不变。
      7. 副本条款: 两份副本各注册监听、各有独立 `_splinter_used` →
         第一次达到 15 金时各交付一张（同一事件内两次 rng 抽取）。

    Test: test_batch_trinkets28.py — 回合收入（`_begin_recruit_for`，
      `INCOME_CAP_BONUS` 抬到 ≥{1}）→ 手牌恰好 1 张金色 T5
      （`is_golden` + `tech_level == 5` + `GILDED_NOT_TRIPLED`）;
      售卖路径（gold=14 + 售 1 只）触发 / `GainGold` 路径触发;
      三条路径**同方法内负对照**（无饰品 → 手牌 0 张）;
      `GainGold(14)` 不触发、再 `+1` 触发（阈值恰好）;
      "一次获得的金币只触发一次": 再次收入 → 仍恰好 1 张（once per
      game）; owner 隔离（对手收入不触发本人、本人收入不触发对手）;
      池占返配平（绑定后交付使该卡池 -1; 出售副本回池 +1 且不发三连
      奖励）; 满手 → `pending_hand_queue` 入队该金色副本（不丢失）;
      Tier 5 池清空 → 落空且 `_splinter_used` 仍为 False（不消耗额度），
      回池后再收入即触发; 两份副本各交付一张; 同 seed 两次对局选中
      同一张卡。

    Params: {1}=num(1)=15（BG32_MagicItem_350; num(0/2/3) 均 None）
            文本字面量 "Tier 5" = _SPLINTER_TIER = 5
    """

    @staticmethod
    def _grant(source, game, hero) -> bool:
        """条件满足则交付一张随机金色 Tier 5 随从（返回是否交付）。"""
        if getattr(source, "_splinter_used", False):
            return False
        if hero.gold < _num(game, source.card_id, 1):
            return False
        cands = _pool_candidates(game, min_tier=_SPLINTER_TIER,
                                 max_tier=_SPLINTER_TIER)
        if not cands:
            return False                     # 池空 → 落空，不消耗额度
        source._splinter_used = True         # 先置位（防嵌套收入重复交付）
        pick = game.rng.choice(cands, label="splinter_of_aurum")
        game.grant_card_copy_to_hand(hero, game.db.get(pick), golden=True)
        return True

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._splinter_used = False

        def cond(hero=None, **kw):
            return hero is h

        def cb(g, hero=None, **kw):
            SplinterOfAurumScript._grant(source, g, hero)

        game.events.register(Listener(event=_GOLD_GAINED, owner=source,
                                      callback=cb, condition=cond))
        return None


# ══════════════ BG32_MagicItem_366 Guiding Candle ══════════════


class GuidingCandleScript:
    """
    Natural language: [x]Your first two <b>Refreshes</b> each turn contain
    only Tier 6 cards. <i>({0} left!)</i>

    Evidence: hearthstone.wiki.gg/Battlegrounds/Guiding_Candle — 32.2.1
      hotfix（2025-05-02, wallii.gg/news/3221-hotfix-patch 转录官方论坛
      公告）"Guiding Candle: Now stacks correctly."（同一次热修同时修
      "Players now shouldn't be offered the same Greater Trinket twice"
      ——多份副本的充能**叠加**）; Wiki tags
      `BACON_REFRESH_TOOLTIP` + `BACON_TRIGGER_XY`（刷新计数型被动）;
      文本 "your Refreshes" 指玩家主动刷新——引擎
      `tavern_refresh(auto=)` 恰好区分主动 / 自动刷新（RULES §7.4.9
      与 Frigid Blossom 口径: `auto=True` 的回合开始/买后自动刷新不是
      "your Refresh"）。EU 论坛帖 12211 亦以 "both charges of Guiding
      Candle" 描述该卡的两点充能。

    Formal spec:
      1. on_bind: `source._candle_left = num(0)`（=2 充能，记在 source
         实体上; 本副本为**协调者**）; 武装
         `hero.set(GameTag.TAVERN_OFFER_TIER_EXACT, 6)`——引擎
         `refresh_tavern` 读取该 hero 级 tag 时把本次刷新的**全部**随从位
         的 min_tier/max_tier 都设为恰好 6（`hsrl2/game.py` L442）。
      2. 副本条款（wiki "stacks correctly"）: on_bind 时若本人已有同卡
         副本充当协调者，则**不再注册监听**，只把 `num(0)` 充能加到
         协调者上（总充能 = 副本数 × num(0)）; 本副本不持有
         `_candle_left`，其 `start_of_turn` 直接返回。
      3. 注册 `tavern_refresh` 持久监听（owner=协调者; condition
         `hero is 本人`）:
           - `auto is True`（自动刷新）: **不消耗**充能; 若仍有充能则
             重新武装 tag（保证接下来的第一次主动刷新仍被覆盖）。
             注意 `start_of_turn` 已在本回合自动刷新**之前**解除武装，
             故自动刷新本身抽到常规档位。
           - `auto is False`（主动刷新）: 充能 >0 时消耗 1 点;
             仍有剩余 → 保持武装; 耗尽 → `hero.clear(TAVERN_OFFER_TIER_
             EXACT)` 恢复常规档位（后续主动刷新按普通规则抽取）。
      4. `start_of_turn`（引擎在回合开始的自动刷新**之前**分发——
         `_begin_recruit_for`: SoT 钩子 → `refresh_tavern(auto=True)`）:
         协调者把充能重置为 `num(0) × 本人同卡副本数`，并**解除武装**
         （清 tag）——若不清，回合开始的自动刷新会被误判为"只出 T6"。
      5. 战斗/淘汰等其它 `refresh_tavern(auto=True)` 调用同样不消耗充能。
      6. 只作用于本人: tag 写在 hero 上，对手酒馆与对手 tag 不变。
      7. 落空语义: 若 Tier 6 池剩余不足，`draw_tavern` 按池给多少算多少
         （官方"刷新内容只有 T6"在池耗尽时不凭空造卡）——充能照常消耗
         （刷新已经发生）。

    Test: test_batch_trinkets28.py — 绑定后（酒馆等级 4）主动刷新 #1/#2
      全部 `tech_level == 6`、#3 无任何 T6（用尽后恢复常规档位）且 tag
      已清; 同方法内负对照（无饰品 → 首次刷新无 T6）; owner 隔离
      （对手刷新的 T6 数 == 0 且对手 tag 未设，本人刷新仍 T6）; 自动
      刷新不计入（`_begin_recruit_for` 的 auto 刷新内容无 T6 且充能仍
      2，随后两次主动刷新仍全 T6）; 跨回合（用尽 2 次后
      `end_recruit_phase()` → 新回合自动刷新无 T6、再两次主动刷新 T6）;
      两份副本叠加（4 次主动刷新全 T6，第 5 次常规）; 同 seed 两次对局
      刷新内容一致。

    Params: {0}=num(0)=2（BG32_MagicItem_366; num(1..3) 均 None）
            文本字面量 "Tier 6" = _CANDLE_TIER = 6
    """

    @staticmethod
    def _coordinator(hero, source):
        """本人已持有的同卡协调者副本（持有 `_candle_left`），无则 None。"""
        for t in hero.trinkets:
            if t is source:
                continue
            if t.card_id == source.card_id \
                    and getattr(t, "_candle_left", None) is not None:
                return t
        return None

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        charge = _num(game, source.card_id, 0)
        coord = GuidingCandleScript._coordinator(h, source)
        if coord is not None:
            # 副本: 充能叠加到协调者，不重复注册监听（wiki "stacks"）
            coord._candle_left += charge
            h.set(GameTag.TAVERN_OFFER_TIER_EXACT, _CANDLE_TIER)
            return None
        source._candle_left = charge
        h.set(GameTag.TAVERN_OFFER_TIER_EXACT, _CANDLE_TIER)

        def cond(hero=None, **kw):
            return hero is h

        def cb(g, hero=None, auto=False, **kw):
            GuidingCandleScript._on_refresh(source, hero, auto)

        game.events.register(Listener(event=TAVERN_REFRESH, owner=source,
                                      callback=cb, condition=cond))
        return None

    @staticmethod
    def _on_refresh(source, hero, auto: bool) -> None:
        left = getattr(source, "_candle_left", 0)
        if auto:
            # 自动刷新不计入、不消耗; 刷新后重新武装下一次主动刷新
            if left > 0:
                hero.set(GameTag.TAVERN_OFFER_TIER_EXACT, _CANDLE_TIER)
            return
        if left <= 0:
            return
        source._candle_left = left - 1
        if left - 1 > 0:
            hero.set(GameTag.TAVERN_OFFER_TIER_EXACT, _CANDLE_TIER)
        else:
            hero.clear(GameTag.TAVERN_OFFER_TIER_EXACT)

    @staticmethod
    def start_of_turn(source, game, ctx):
        if getattr(source, "_candle_left", None) is None:
            return None                      # 非协调者副本（充能已并入）
        h = source.controller
        if h is None:
            return None
        copies = sum(1 for t in h.trinkets if t.card_id == source.card_id)
        source._candle_left = _num(game, source.card_id, 0) * copies
        h.clear(GameTag.TAVERN_OFFER_TIER_EXACT)   # 自动刷新前解除武装
        return None


# ══════════════ BG32_MagicItem_419 Yu'lon Sticker ══════════════


class YulonStickerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Make your highest-Tier
    Dragon Golden.

    Evidence: hearthstone.wiki.gg/Battlegrounds/Yu'lon_Sticker（Wiki tags
      `START_OF_COMBAT`; Related cards "Generates BG24_004"? 无——本卡无
      `evolution_card_id`，效果自含）无 Notes 反证; 官方对"金色化是否跨
      战斗保留"的预期 = **永久卡身份变更**（Blizzard 论坛 Bug Report
      "Persistent Poet does not keep Dragons golden after combat"
      2025-07-12 多玩家确认 Yu'lon 的金色化在下一招募阶段仍为金色）。
      引擎 2026-09-02 落地 `game._combat_transforms` 战后重放（RULES
      §3.5 例外 / §6.21; `hsrl2/tests/test_engine_primitives.py::
      TestCombatTransformPersistence`）→ 本卡可迁移。
      并列取最左（棋盘顺序）——同族"最高 Tier 并列"裁定先例
      `BG27_Reward_508`（batch_quest_rewards）。

    Formal spec:
      1. `start_of_combat`（饰品 SoC 钩子; 引擎分发顺序 饰品→奖励→随从）:
         候选 = 本人棋盘**存活**、`race ∈ {DRAGON, ALL}`（Amalgam 视为
         龙，RULES §6.18）、**非金色**（已金色不再重复金色化）、
         `db.golden_version(def)` 存在、且未带 `GILDED_NOT_TRIPLED`
         的随从。
      2. 取候选最高 `tech_level` 档; 该档内**最左**者（棋盘列表顺序）
         为唯一目标——`game.rng` **不**参与（无随机性，确定性）。
      3. 目标经 `batch_battlecry._goldenize` 金色化: `Transform` 到
         **金色独立卡定义**（`db.golden_version`）、`keep_buffs=True`
         保留原附魔、补 `GOLDEN` + `TRIPLE_BASE_CARD_ID` 并打
         `GILDED_NOT_TRIPLED`（Reno 口径: 出售/淘汰回池 1 份基础卡，
         不发三连奖励）。
      4. **跨战斗持久**: `Transform` 在战斗内记入 `game._combat_transforms`
         （`hsrl2/actions/stats.py`），`run_combat` 复原棋盘后按
         old_uuid 原位换回新实体（清 DEAD / 攻击资格、血量回满）并重跑
         `on_transform` → 金色化在下一招募阶段保留（官方预期）。
      5. 空候选（无龙 / 全为已金色）→ 落空（不创建实体、不消耗资源）。
      6. 只作用于本人棋盘（对手龙不变）; 副本条款: 两份副本各注册 SoC
         → 同一场战斗内先后各自金色化（第一份使最高档变金，第二份
         作用于剩余最高档非金龙）。
      7. 每场战斗独立触发: 上一场已金色的龙不再入选，下一场继续金色化
         剩余最高档龙。

    Test: test_batch_trinkets28.py — 真实 `run_combat` 内探针
      （`start_of_combat` 事件在 SoC 钩子后广播）: T6 龙变金
      （`is_golden` + `card_id == golden_version(BG24_004)` +
      `TRIPLE_BASE_CARD_ID`），T3 龙**未**变金（正/负对照同方法）;
      战后金色化仍在（跨战斗持久——本卡迁移的核心契约，旧实现此处
      被快照回滚）; 非龙随从与**对手**龙不变; 无饰品对照全不变;
      并列最高档取最左; 已金色龙不重复入选（下次金色化 T3）;
      先金色化一次再跑第二场 → 又一只变金; 两份副本各金色化一只;
      空龙棋盘落空且池不变; `GILDED_NOT_TRIPLED` 出售回池 1 份;
      真实 `end_recruit_phase` 触发 SoC。

    Params: 无模板参数（BG32_MagicItem_419 num(0..3) 全 None）
    """

    @staticmethod
    def _candidates(game, hero):
        out = []
        for m in hero.board:
            if m.dead:
                continue
            if m.race not in _DRAGON_RACES:
                continue
            if m.is_golden or m.has(GameTag.GILDED_NOT_TRIPLED):
                continue
            d = game.db.get(m.card_id)
            if d is None or game.db.golden_version(d) is None:
                continue
            out.append(m)
        return out

    @staticmethod
    def start_of_combat(source, game, ctx):
        from hsrl2.scripts.batches.batch_battlecry import _goldenize
        h = source.controller
        if h is None:
            return None
        cands = YulonStickerScript._candidates(game, h)
        if not cands:
            return None
        best = max(m.tech_level for m in cands)
        pick = next(m for m in cands if m.tech_level == best)   # 并列取最左
        _goldenize(game, pick)
        return None


# ══════════════ DEFERRED（不注册; 仅 docstring 台账） ══════════════


class RewinderPortraitScript:
    """
    Natural language: [x]Get a Soul Rewinder and a Wrath Weaver. Your Soul
    Rewinders also gain Attack.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires 多关联卡数据链 + 家族级"给予者加成"读取点
      与 Attack 增量权威

    Dependency:
      1. 条款一 "Get a Soul Rewinder **and** a Wrath Weaver": 数据链
         `CardDef.evolution_card_id`(100949) 只指向 `BG26_174` Soul
         Rewinder（池 T2，**已注册**）; Wrath Weaver 无第二条数据链
         （XML `TAG_SCRIPT_DATA_NUM_1`(4185)=2 的语义是"生成卡数"，
         非第二卡 dbid; Bronzebeard Portrait 同为 2、Jewelry Box=1
         佐证）。命名回退（batch_trinkets25 `_related_card` 模式）可
         解析唯一名，但见 2。
      2. 条款二 "Your Soul Winders **also gain Attack**": 增量**数值无
         权威**——`BG26_174`/`BG26_174_G` 的 CardDef num 全 None
         （既有脚本 `batch_econ_misc.SoulRewinderScript` 的 "+1 Health"
         / 金色 "+2" 是文本字面量），本饰品 CardDef 亦无任何模板参数;
         wiki 卡页（Rewinder Portrait / Soul Rewinder）无 Notes，
         32.x–36.x 补丁说明无该卡数值记录 → "等于 Health 增量"只是
         候选读法（SOP §6b 第 4 步: 无证据不得拍板）。
      3. 即使取候选读法，读取方必须是 `SoulRewinderScript` 内
         （hero 级标记消费点），本批不可写他批次脚本（SOP §12 item 2
         "禁读/重放他脚本私有记账" + item 14 "不得复刻他卡数值权威"）;
         在饰品侧另注册 HERO_DAMAGE_TAKEN 重放 = 归属错误 + 近似实现。
    Implementation path: (a) 数据层补"Get A and B"第二关联卡（生成器导出
      第二个 `BACON_EVOLUTION_CARD_ID` 或主线裁定命名回退）; (b) 官方
      增量权威（wiki Notes / 多语言文本 / 实测）落地; (c) `SoulRewinder
      Script` 增读 hero 级 `soul_rewinder_bonus_atk`（本饰品 on_bind
      写入）并把 Buff 的 atk 一并施加。阻塞卡: BG30_MagicItem_868。
    Reference: batch_trinkets12 模块 docstring（同卡既有台账，本轮复评
      维持——新落地的 `gold_gained` 与本卡无关）。

    Test: 不注册（DEFERRED）——台账守卫见
      test_batch_trinkets28.py::TestRegistryLedger（CardDB 有定义但不在
      REGISTRY）。

    Params: 无模板参数（BG30_MagicItem_868 num(0..3) 全 None）
    """


class FelbloodPortraitScript:
    """
    Natural language: Get a Slimy Felblood. Your Fiery and Slimy Felbloods
    give Attack <i>and</i> Health.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires 载荷脚本（RULES §7.4.6 例外条）

    Dependency:
      1. 关联卡 `BG29_873` Slimy Felblood（战吼: 酒馆随从 +2 生命 this
         game）与 `BG29_877` Fiery Felblood（亡语: 酒馆随从 +2 攻击
         this game）在 REGISTRY **均无脚本**（36.2.2 数据核实）→ 交付
         的 Felblood 永不产生"给予"行为，"give Attack **and** Health"
         的改写对象不存在。
      2. "give Attack and Health" 的读取点是这两个脚本的 `TavernBuff`
         出口（须读 hero 级双属性标记），本批不可写他批次脚本
         （SOP §12 item 2）。
    Implementation path: 先迁 `BG29_873`（战吼 → `TavernBuff` 持久酒馆
      Buff +2 生命）与 `BG29_877`（亡语 → `TavernBuff` +2 攻击，含金色
      `BG29_873_G`/`BG29_877_G`）; 随后由它们读 hero 级
      `felblood_extra_health` / `felblood_extra_atk`（本饰品 on_bind
      写入 + 数据链交付）把缺失的一侧补上。阻塞卡: BG30_MagicItem_869。
    Reference: batch_trinkets12 模块 docstring（同卡既有台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_869 num(0..3) 全 None）
    """


class RedeemerPortraitScript:
    """
    Natural language: [x]Get a Nalaa the Redeemer. Your Nalaa the
    Redeemers give an extra +{0}/+{1}.

    Status: DEFERRED — requires 载荷脚本的"extra"消费通道（RULES §7.4.6
      例外条 + SOP §12 item 2/14）

    Dependency:
      1. 关联卡 `BG28_551` Nalaa the Redeemer（"Whenever you cast a
         Tavern spell, give a friendly minion of each type +{0}/+{1}"，
         num(0)=4 / num(1)=3）已由并行批 `batch_payload_minions`
         （工作区 2026-09-11）注册——本体可交付。
      2. 但其 `on_cast` 回调直接 `_each_type_buffs(...)` 结算，
         **不读**任何 hero 级"extra"标记; 本饰品无法在不改该脚本的前提
         下把"extra +4/+4"并入同一次 give。在饰品侧重放
         `tavern_spell_cast` 并自行复刻 Nalaa 的"每族随机一只"选取 =
         复刻他卡逻辑与 rng 消耗（近似实现，SOP §6b/§12 item 14 禁止）。
      3. 增量数值**本身有权威**（本饰品 num(0)=num(1)=4）。
    Implementation path: `NalaaTheRedeemerScript.on_cast` 增读 hero 级
      `nalaa_extra_atk` / `nalaa_extra_health`（本饰品 on_bind 写入 +
      数据链交付）并把额外值并入同一次 `_each_type_buffs`。阻塞卡:
      BG30_MagicItem_944。
    Reference: batch_trinkets24 模块 docstring（同卡既有台账）;
      `batch_payload_minions.NalaaTheRedeemerScript`。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=4 {1}=num(1)=4（BG30_MagicItem_944）
    """


class EnforcerPortraitScript:
    """
    Natural language: [x]Get a Lightfang Enforcer. Your Lightfang
    Enforcers have all minion types.

    Status: DEFERRED — requires 运行时"追加全类型身份"协议（`RACES` /
      家族作用域读取点; ENGINE_BACKLOG §A1）

    Dependency:
      1. 关联卡 `BGS_009` Lightfang Enforcer（EoT: 给每种类型的友方
         随从 +4/+4）已由并行批 `batch_payload_minions`（工作区）注册
         ——本体可交付、EoT 行为就绪。
      2. "Your Lightfang Enforcers **have all minion types**" 需要给
         **家族**（含绑定后新获得的副本）追加全类型身份。引擎
         `GameTag.RACE` 是单值: 直接 `m.set(RACE, Race.ALL)` 只在
         `create_minion` 的异变通道（Incubation Mutation "Minions with
         no type have all minion types"）有生产点，**没有**"按卡家族
         追加身份"的光环读取点在绑定后持续生效（`hero.race_auras` 是
         属性光环不是身份改写）; 入场即打标 = 漏掉 Transform/直接
         `board[idx]=` 等非 summon 入板路径（SOP §16b item 32 禁止）。
      3. 是否等于 `Race.ALL` 语义（"匹配一切类型"）本身需主线裁定
         （ENGINE_BACKLOG §A1 与 `_179`/`_418`/`_825` 同族）。
    Implementation path: (a) `RACES` 集合/位掩码 tag + 全部 race 读取点
      改造（`Minion.race` → 集合视图 + 单值兼容读取），或 (b) 引擎
      `game.add_card_aura`（ENGINE_BACKLOG §B2-17）式的家族身份读取点;
      随后本饰品 on_bind 数据链交付并对家族实例追加全类型身份。
      阻塞卡: BG30_MagicItem_971（同族 _179 / _418 / _825）。
    Reference: docs/agents/ENGINE_BACKLOG.md §A1/§B2-4; batch_trinkets24
      模块 docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_971 num(0..3) 全 None）
    """


class BalladistPortraitScript:
    """
    Natural language: [x]Get a Lovesick Balladist. At the start of each
    turn, get another. Your Lovesick __Balladists also give Attack.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires "also give Attack" 的增量权威 + 他批次
      脚本读取点

    Dependency:
      1. 关联卡 `BG26_814` Lovesick Balladist（池 T4）**已注册**
         （`batch_battlecry`）; "At the start of each turn, get another"
         条款本身可交付（占池 + `grant_card_copy_to_hand`）。
      2. 但 "also give Attack" 的**增量无数据字段**: `BG26_814` 的
         CardDef 文本第二段（`@` 后）为 "Battlecry: Give a Pirate
         +{0}/+{1}"，然而 base 与 golden 两个定义
         `num(0) is None`（实测），本饰品 CardDef 无任何模板参数
         （num(0..3) 全 None）→ Attack 数值无权威。已查信源:
         hearthstone.wiki.gg（Balladist Portrait / Lovesick Balladist，
         无 Notes，仅 [Targeted] 与 34.6 "+0→+1 Health" 变更记录）、
         官方 32.2.3/34.6/35.x 补丁说明、Bug 报告帖 —— 均未给出增量
         （SOP §6b 第 4 步: 无证据不实现）。
      3. 读取点必须在 `LovesickBalladistScript`（他批次）内，本批不可
         写（SOP §12 item 2/14）。
    Implementation path: 权威落地后——(i) on_bind 注册 `start_of_turn`
      监听 → `game.grant_card_copy_to_hand(hero, db.get("BG26_814"))`
      （池随从占池、满手入队）; (ii) `LovesickBalladistScript` 读 hero
      级 `balladist_extra_atk`（本饰品 on_bind 写入）并在 battlecry 的
      Buff 上补同额 Attack。阻塞卡: BG30_MagicItem_987。
    Reference: batch_trinkets24 模块 docstring（同卡既有台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_987 num(0..3) 全 None）
    """


class YoggTasticPastryScript:
    """
    Natural language: Spin the Wheel of Yogg-Saron. At the start of each
    turn, spin it again.

    Status: DEFERRED — requires Wheel of Yogg-Saron 子系统 + 结果表

    Dependency:
      1. 全库无 Wheel 实现（`grep -rni "spin_wheel" hsrl2/` 只命中他批
         DEFERRED docstring）; 数据中亦无轮盘结果 token/表
         （`grep -i "wheel" data/*.json` 只命中无关卡名 Dalaran Cheese
         Wheel / Water Wheel）。
      2. 同缺口已由 batch_quest_rewards3（BG24_Reward_135
         Yogg-tastic Tasties）与 batch_anomalies3（BG27_Anomaly_503
         The Yogg-iseum）备案; 官方未公布结果概率表。
    Implementation path: 引擎实现 `game.spin_wheel(hero)` + 每个结果的
      card_id/数值数据权威（官方奖池表）→ 本卡 on_bind 调用一次、
      `start_of_turn` 每次回合再调用。阻塞卡: BG30_MagicItem_994。
    Reference: docs/agents/ENGINE_BACKLOG.md §B11。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_994 num(0..3) 全 None）
    """


class DrakkariPortraitScript:
    """
    Natural language: [x]Get a Drakkari Enchanter. Your Drakkari
    Enchanters are both Mechs and Elementals.

    Status: DEFERRED — requires 多值种族 `RACES`

    Dependency:
      1. 关联卡 `BG26_ICC_901` Drakkari Enchanter（池 T5，EoT 翻倍为
         引擎内建光环）**已注册** → 交付侧就绪。
      2. 但 "are **both** Mechs and Elementals" 是**同时属于两个类型**:
         `GameTag.RACE` 单值，`Race.ALL` 是"匹配一切"——用它会把
         Drakkari 错误地变成 Beast/Dragon/Quilboar/… 全部类型（超出
         文本给出的两个）。
    Implementation path: ENGINE_BACKLOG §A1 的 `RACES` 集合 tag +
      `Minion.race` 集合视图（单值兼容读取点全改造）; 改造后 on_bind =
      数据链交付 + 对本人 Drakkari Enchanter **实例**追加
      {MECH, ELEMENTAL}（未来副本经入板钩子）。阻塞卡:
      BG32_MagicItem_179（同族 _971 / _418 / _825）。
    Reference: docs/agents/ENGINE_BACKLOG.md §A1; batch_trinkets24 模块
      docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_179 num(0..3) 全 None）
    """


class BristlebachPortraitScript:
    """
    Natural language: [x]Get a Bristlebach. Your Bristlebachs play
    <b>Blood Gems</b> on all friendly minions.

    Status: 已迁出 → batch_trinkets34（2026-09-13，RULES §7.4.16 家族行为开关通道 `hero.family_flags`）; 原阻塞: requires 载荷脚本的 target-scope 消费通道
      （RULES §7.4.6 例外条 + SOP §12 item 2/14）

    Dependency:
      1. 关联卡 `BG26_157` Bristlebach（非池 T6，"Avenge (2): This plays
         2 Blood Gems on all your Quilboar"）已由并行批
         `batch_payload_minions`（工作区）注册——Avenge 行为就绪。
      2. 但其 `avenge` 钩子把目标集**写死**为
         `race in (QUILBOAR, ALL)`，不读任何 hero 级 target-scope 标记;
         在饰品侧再注册一次 Avenge/重放会让野猪人**双倍**吃宝石
         （本体已给 2 颗），且复刻他卡效果（近似实现，SOP §6b/§12
         item 14 禁止）。Bristlebach 本体不是池卡，只能由本饰品交付，
         但目标集改写点仍在其脚本内。
    Implementation path: `BristlebachScript.avenge` 读 hero 级
      `bristlebach_all_friendly`（本饰品 on_bind 写入 + 数据链交付）
      决定目标集为全体友方。阻塞卡: BG32_MagicItem_274。
    Reference: batch_trinkets24 模块 docstring（同卡既有台账）;
      `batch_payload_minions.BristlebachScript`。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_274 num(0..3) 全 None）
    """


class CzarinaPortraitScript:
    """
    Natural language: Get a Charging Czarina. Your Charging Czarinas also
    give Health.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires Health 增量权威 + 他批次脚本读取点

    Dependency:
      1. 关联卡 `BG28_741` Charging Czarina（池 T5，"Whenever you cast a
         Tavern spell, give your minions with Divine Shield +{0}
         Attack"，num(0)=4）**已注册**。
      2. "also give Health" 的**增量无数据字段**: base/golden/本饰品三个
         CardDef 均无 Health 参数（`BG28_741` 只有 num(0)=4; 饰品
         num(0..3) 全 None）; wiki 卡页无 Notes → 候选读法（等于
         Attack 增量 / 固定 +1 / 隐藏常量）无证据可裁（SOP §6b 第 4
         步）。
      3. `batch_econ_misc.ChargingCzarinaScript` 只给 Attack、不读任何
         加成通道; 在饰品侧另注册 `spell_resolved` 重放 = 归属错误
         （Czarina 被出售后仍生效）+ 复刻他卡数值权威（近似，SOP §6b
         禁止）。
    Implementation path: 权威落地后 `ChargingCzarinaScript` 读 hero 级
      `czarina_extra_health`（本饰品 on_bind 写入 + 数据链交付）并在
      同一次 Buff 上补 Health。阻塞卡: BG32_MagicItem_283。
    Reference: batch_trinkets24 模块 docstring（同卡既有台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_283 num(0..3) 全 None）
    """


class PutricideStickerScript:
    """
    Natural language: [x]Craft a custom Undead. At the start of every 2
    turns, repeat this. <i>({0} |4(turn, turns) left!)</i>

    Status: DEFERRED — requires Craft（多步部件合成）选择链

    Dependency:
      1. "Craft a custom Undead" 是 Putricide 多步部件合成链（种族 +
         关键词 + 属性选择 → `BG25_HERO_100pt` token）; 全仓无 `craft`
         实现（`grep -rni "def craft" hsrl2/` 零命中），
         `BG25_HERO_100p` Build-An-Undead 技能亦因此 DEFERRED
         （batch_hero_combat3 台账）。
      2. 数值 `{0}`=num(0)=2 已就绪; 周期触发（每 2 回合）本身可表达，
         但合成链缺失 = 半实现 → 第三态（SOP §6b）。
    Implementation path: 建立多步 `PendingChoice` 合成协议（部件卡片池 +
      参数落点 + token 生成）后，on_bind 与每 `{0}` 回合的
      `start_of_turn` 各调用一次。阻塞卡: BG32_MagicItem_300 +
      `BG25_HERO_100p`。
    Reference: docs/agents/ENGINE_BACKLOG.md §B10。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=2（BG32_MagicItem_300）
    """


class TarecgosaStickerScript:
    """
    Natural language: [x]Your left and right-most Dragons permanently keep
    <b><b>Bonus Keyword</b>s</b> and stats gained in combat.

    Status: DEFERRED — requires Bonus Keyword 定义域 + 位置/种族 PERSIST
      光环原语（双重阻塞）

    Dependency:
      1. "Bonus Keyword" 定义域无任何数据字段（RULES §9.6 主线裁定;
         官方定义域已收为 DS/Reborn/Stealth/Taunt/Venomous/Windfury 6
         张——`BG36_MagicItem_801` Consuming Claw 已按该 6 集实现），
         且需**逐实体记录被授予的 bonus 关键词**（"keep" 的对象）。
      2. 引擎 PERSIST 是**单实体全量** tag（`PERSIST_COMBAT_CHANGES`，
         Tarecgosa / Persistent Poet 本体）; 无"按位置（最左/最右）+
         种族（Dragon/ALL）持续授予"的光环原语，`run_combat` 的 Poet
         通道只覆盖"相邻龙"（`ADJACENT_PERSIST_SOURCE`）。用入场即
         buff/逐实例打标的近似被 SOP §16b item 32 禁止（Transform /
         直接入板路径会漏）。
    Implementation path: (a) `BONUS_KEYWORD_SET` 权威落数据字段 + 逐实体
      `BONUS_KEYWORDS_GRANTED` 记录; (b) "位置 + 种族"的 PERSIST 光环
      读取点（与 `hero.race_auras` / `game.add_tier_aura` 同构的
      "读取时校验 source 在场"生命周期）。阻塞卡: BG32_MagicItem_417
      （同族 _891 / _892）。
    Reference: docs/BATTLEGROUNDS_RULES.md §9.6;
      docs/agents/ENGINE_BACKLOG.md §B9。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_417 num(0..3) 全 None）
    """


class MacawPortraitScript:
    """
    Natural language: Get a Monstrous Macaw. Your Monstrous Macaws also
    trigger your left-most <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets36（2026-09-13，RULES §7.4.17 条件化
      战吼第二消费者）; 原阻塞: requires 载荷脚本的 extra-battlecry 消费
      通道 + "最左战吼"选定口径（RULES §7.4.6 例外条 + SOP §12 item 2/14）

    Dependency:
      1. 关联卡 `BGS_078` Monstrous Macaw（非池 T4，"Rally: Trigger your
         left-most Deathrattle (except this minion's)"）与金色
         `TB_BaconUps_135` 已由并行批 `batch_payload_minions`（工作区）
         注册——Rally/亡语侧就绪。
      2. 原阻塞（2026-09-13 消除）: 其 `rally` 钩子只触发最左**亡语**，
         且"最左 Battlecry"资格集口径无权威。现已由 RULES §7.4.17
         条件化战吼协议补齐读取点（`FLAG_MACAW_EXTRA_BATTLECRY`），
         资格集 = 最左**带战吼**者（32.2 论坛复现串 `M G x B y z`）。
    Implementation path: `MonstrousMacawScript.rally` 读
      `FLAG_MACAW_EXTRA_BATTLECRY` 在 Rally 时对最左带战吼随从执行
      `TriggerBattlecry`（已落地，见 batch_trinkets36）。
    Reference: batch_trinkets15/24 模块 docstring（同卡既有台账）;
      `batch_payload_minions.MonstrousMacawScript`。

    Test: 已迁出（batch_trinkets36 于 2026-09-13 注册该饰品）——原台账
      守卫见 `test_batch_trinkets29.py`。

    Params: 无模板参数（BG32_MagicItem_803 num(0..3) 全 None）
    """


class SelflessPortraitScript:
    """
    Natural language: [x]Get a Selfless Hero. Your Selfless Heroes also
    trigger on <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
      条件化战吼协议）; 原阻塞: requires 载荷脚本的 battlecry 附加消费
      通道（RULES §7.4.6 例外条 + SOP §12 item 2/14）

    Dependency:
      1. 关联卡 `BG_OG_221` Selfless Hero（非池 T2，"Deathrattle: Give a
         random friendly minion Divine Shield"）与金色
         `TB_BaconUps_014` 已由并行批 `batch_payload_minions`（工作区）
         注册——亡语侧就绪。
      2. 但其脚本只实现 `deathrattle`，**不读** hero 级标记、也没有
         `battlecry` 分支; 在饰品侧监听 `battlecry_trigger` 重放圣盾
         授予 = 复刻他卡亡语逻辑（含金色 `_targets` 私有类属性与
         `rng.sample` 消耗），近似实现（SOP §6b/§12 item 14 禁止）。
    Implementation path: `SelflessHeroScript` 读 hero 级
      `selfless_extra_battlecry`（本饰品 on_bind 写入）并实现 `battlecry`
      分支（复用同一 `deathrattle` 结算函数）。阻塞卡:
      BG32_MagicItem_804。
    Reference: batch_trinkets15/24 模块 docstring（同卡既有台账）;
      `batch_payload_minions.SelflessHeroScript`。

    Test: 已迁出（batch_trinkets35 于 2026-09-13 注册该饰品）——原台账
      守卫见 `test_batch_trinkets29.py`。

    Params: 无模板参数（BG32_MagicItem_804 num(0..3) 全 None）
    """


class BattlecruiserPortraitScript:
    """
    Natural language: [x]Get an 12/12 Battlecruiser. Whenever the Tavern is
    <b>Refreshed</b>, add a Battlecruiser Upgrade to it.

    Status: DEFERRED — requires Battlecruiser Upgrade 附着子系统（三重阻塞）

    Dependency:
      1. 关联卡 `BG31_HERO_801pt` Battlecruiser（token，数据 2/2）在
         REGISTRY **无脚本**，且本卡要求交付时属性为 **12/12**
         （文本字面量覆盖）——需"SetStats 语义"的交付体。
      2. "Battlecruiser Upgrade" 是独立子系统（10 张
         `BG31_HERO_801pta..j` card_type=42 存在，但 Jim Raynor
         `BG31_HERO_801p` 整条技能链 DEFERRED，batch_hero_combat3
         台账）; db 无 Upgrade 的数据链（`evolution_card_id` 只指向
         Battlecruiser 本体）。
      3. "add … **to it**" 是**馆内/棋盘已有卡追加部件**协议——
         `inject_tavern_minion` / `add_tavern_entity` 只能放入新实体，
         无法表达"给同一实体挂载升级件"。
    Implementation path: 先实现 Jim Raynor 的 Upgrade 商店/附着协议
      （部件卡池 + 逐实体 upgrade 列表 + 刷新时追加），再交付 12/12
      Battlecruiser。阻塞卡: BG32_MagicItem_806 +
      `BG31_HERO_801p`。
    Reference: docs/agents/ENGINE_BACKLOG.md §B2-13; batch_trinkets15/24
      模块 docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_806 num(0..3) 全 None;
            "12/12" 为文本字面量，无数据字段）
    """


class GemDonationScript:
    """
    Natural language: [x]The first minion you sell each turn plays its
    <b>Blood Gems</b> on the 3 highest-Tier minions in the Tavern.

    Status: DEFERRED — "plays its Blood Gems" 的**宝石枚数/来源**无权威
      读法（SOP §6b 第 4 步）

    Dependency:
      1. 三种候选读法在野猪人高宝石局面数值差异巨大:
           (a) 按该随从身上的 `GEMS_PLAYED_ON` 枚数 N、每颗对 3 个目标
               各施放一次（共 3×N 颗）;
           (b) 共 N 颗轮转分配到 3 个目标;
           (c) 每目标固定 1 颗（共 3 颗）。
      2. 已查信源（本轮复读，无新证据）: hearthstone.wiki.gg 卡片页
         （仅 refTags "Blood Gem-related / Tavern Tier-related /
         Selling-related" 与 [Targeted]/[Random] 标签，**无 Notes
         段**）、36.2.2 / 35.6 patch notes、中文卡库镜像
         （wiki.ifindhs / hs.istudylinux）——均无裁定。
      3. 引擎侧**已就绪**（非引擎缺口）: `minion_sold` 事件
         （`Game.sell_minion` 广播）、per-minion `GEMS_PLAYED_ON`
         tag、`PlayBloodGems` action、`MINIONS_SOLD_THIS_TURN` hero 级
         计数（本回合首售判定）。裁定后分钟级实现。
    Implementation path: 监听 `minion_sold` + 本回合首售记账（source
      级闭包）→ 取本人酒馆 `tech_level` 最高的 3 只（并列按位置/rng
      口径）→ 按裁定读法施放。阻塞卡: BG32_MagicItem_809。
    Reference: docs/agents/ENGINE_BACKLOG.md §C（AMBIGUOUS 留档）;
      batch_trinkets15/25 模块 docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_809 num(0..3) 全 None;
            文本字面量 "3 highest-Tier minions" 未实现前不入代码）
    """


# ══════════════ 注册 ══════════════


def register() -> List[str]:
    """注册本批 3 张 CORRECT 饰品（15 张 DEFERRED 不注册）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (SPLINTER_OF_AURUM, SplinterOfAurumScript),
        (GUIDING_CANDLE, GuidingCandleScript),
        (YULON_STICKER, YulonStickerScript),
    ]
    registered: List[str] = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
