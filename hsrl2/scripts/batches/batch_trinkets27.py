"""批次 trinkets27 — 饰品第二十七批（作业单 2026-09-14，18 张）。

台账来源: 作业单给定的 18 个 id（`docs/agents/TRINKET_LEDGER.md` **片 1**
的完整一行 + `BG30_MagicItem_402/416/418/423/431/439/440/548/701/707/711/
777/803/804/821t2/822/825/828`）。运行核验（`CardDB` 实读）:
18/18 在 `CardDB` 存在，18/18 在 `CardDB.trinket_offer_pool()` 中
（商店可提供成员——含 `BG30_MagicItem_821t2` Fishy Sticker，其 `t2`
后缀**无同名本体**，故不是升级变体，是独立商店本体）。本批注册集合与
既有 batch_trinkets1..26 互不相交。

18 张**全部**曾在本批前出现在旧批的 DEFERRED 台账中（402/416/418/423/
431/439/440 → `batch_trinkets11` 模块 docstring + 类 docstring;
548/701/707/711/777/803/804/821t2/822/825/828 → `batch_trinkets12`）。
本轮按引擎现状**逐张复评**（SOP §6b 二态铁律），旧台账中已被后续引擎
提交补齐的依赖据实解冻，仍缺依赖的原样维持 DEFERRED。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码——`_num`）；
关联卡一律走数据链 `CardDef.evolution_card_id` → `CardDB.by_dbf`
（RULES §7.4.6，零硬编码卡 id）；随机一律 `game.rng`；状态写在
source 实体属性 / 监听闭包（**无 game 级 flag**——SOP §12 item 9）。

**本轮新引擎原语复核**（作业单列出的"可能解冻"清单，逐张实测后裁决）:
  - **展示位档位协议**（`hsrl2/game.py::refresh_tavern`，
    commit 66eaa35）: `GameTag.TAVERN_OFFER_TIER_EXACT`（全部随从位取自
    恰好该档，优先于 Elven Elite）+ `GameTag.TAVERN_EXTRA_TIER_SLOTS` /
    `GameTag.TAVERN_EXTRA_TIER`（额外 N 位取自恰好该档，**缺省
    `tavern_tier + 1` 且封顶 `game.max_tavern_tier`**）→ **解冻
    `BG30_MagicItem_423` Innkeeper's Stein**（旧台账"上界恒等于酒馆
    等级，无法让某一个额外展示位从 tier+1 抽取"已过期）。
  - **`spell_resolved` vs `spell_resolving`**（RULES §7.4.12，两个时点）
    → **解冻 `BG30_MagicItem_548` Glowscale Portrait** 的第二条款
    （"**After** you cast a Spellcraft spell" 是**后置**语义，必须监听
    `spell_resolved`；`spell_resolving` 是结算前，会让本次施放自己吃到
    刚触发的加成）。同族已验收先例: Coral Spear `BG35_MagicItem_925`
    （`spell_resolving` 用于"Whenever you cast a Spellcraft spell"，
    本卡是 "After" 故取后置）。
  - **以生命代金购买协议**（RULES §7.4.7，commit 690ded8）: 三条来源含
    **实体级 `GameTag.HEALTH_BUY`**（给当前酒馆中的实体打标，`buy_from_
    tavern` 统一判定并在成交时消费）+ **`tavern_entity_added`** 入馆
    观察点（RULES §7.4.9）→ **解冻 `BG30_MagicItem_701` The Eye of
    Sargeras**（旧台账"引擎只有 CardDef 静态 `health_cost`，无'按购买
    次数切换支付方式'的运行时标记与消费点"已过期——实体级 HEALTH_BUY
    正是该运行时标记，且**不污染** hero 级配额 tag，避免 SOP §16b
    item 28/29 的"多来源共用同一份状态"缺陷）。
  - 其余原语逐个核对: `gold_gained`（无本批卡消费——402 的
    "gain 4 Gold" 属载荷卡且被弃牌系统阻塞）、
    `MINIONS_SOLD_THIS_TURN`（无本批卡）、`trigger_deathrattle` /
    `grant_combat_deathrattle` / `destroy_minion`+`minion_destroyed`
    （无本批卡）、`add_tier_aura`（无）、`add_permanent_spellcraft_rule`
    （无）、`add_tavern_entity`（701 使用——见上）、`cast_spell_effect`
    （无）、`grant_card_copy_to_hand`（777/548 走
    `grant_trinket_related_card` 统一入口）、`Transform.on_transform`
    （416 仍被"两段定向选择链"阻塞，与 on_transform 无关）、
    `run_combat` 恢复 `_magnetic_stack`（无）、
    `racefx.elemental_give_bonus`（431 是"改写另一张卡的行为"，
    与元素 give-stats 出口无关）、`COUNTER_ELEMENTALS_PLAYED`（无）、
    `_pair_gifts`（无）= **均不能解冻对应卡**。

注册 3 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG30_MagicItem_423 Innkeeper's Stein — on_bind 置 hero 级
      `TAVERN_EXTRA_TIER_SLOTS += 1`（**不**写 `TAVERN_EXTRA_TIER`:
      文本只说"a higher Tier"，引擎缺省 = `min(tavern_tier + 1,
      max_tavern_tier)`，即"高一档且不越 T7 上限"——写入一次性值会把
      绑定时的 `tavern_tier+1` 冻结、并在酒馆等级 6 时越档到 T7）。
      `refresh_tavern` 在常规抽取之外独立
      `draw_tavern(extra_tier, extra_slots, min_tier=extra_tier)`
      （池占返/金馆金色化/持久酒馆 Buff 全部走同一路径）。

  BG30_MagicItem_548 Glowscale Portrait — on_bind:
      (1) 数据链交付关联卡 `BG34_Giant_035` Timewarped Glowscale
          （token → 零池操作、白板副本、满手入等待队列——RULES §7.4.6）;
      (2) 注册 `spell_resolved` 持久监听（owner=饰品）: `spell.has(
          SPELLCRAFT)` ∧ `spell.controller is 绑定者` →
          对本人**全部存活且带 Divine Shield** 的随从
          `Buff(atk=num(0), health=num(1))`（印面 +3/+3）。

  BG30_MagicItem_701 The Eye of Sargeras — on_bind:
      (1) 滚动计数本人**购买**的卡（`minion_bought` / `spell_bought`
          两个真实生产点，hero 作用域过滤）——每 num(0) 张一轮;
      (2) 计到第 `num(0) - 1` 张时**武装**: 给当前酒馆内全部实体
          （随从 + 法术）打**实体级** `GameTag.HEALTH_BUY`，并注册
          `tavern_entity_added` 在武装期给新入馆实体补标（RULES §7.4.9
          顺序无关）——于是"第四张买的卡"在 `buy_from_tavern` 的
          以生命代金分支成交时支付生命（RULES §7.4.7 来源 2）;
      (3) 第 num(0) 张买入后**解除武装**: 只清除**本次自己打过**的
          标记（uuid 集——不碰其它来源设的 HEALTH_BUY，SOP §16b
          item 28/29 纪律），计数归零滚动重来。

DEFERRED 7 张 → **5 张**（**不注册**；Status / Dependency / Implementation
path 逐张见各类 docstring，禁止第三态——SOP §6b）。
**2026-09-21 迁出 2 张**: 418 Bronzebeard / 825 Smuggler Portrait 由
`batch_family_races` 注册（RACES 家族类型身份改写 + Tavern/Discover
作用域）。
（本批原始 15 张；828/944/274/803/804/933/777 等已相继注册迁出——
803 Kaboom Bot Portrait 于 2026-09-18 由 batch_trinkets39 注册）
═══════════════════════════════════════════════════════════════════════
  - BG30_MagicItem_402 Conductor Portrait — 全仓零弃牌机制
    （`CARD_DISCARDED` + `game.discard_card`）; 载荷 `BG28_585`
    Snarling Conductor 亦未注册。
  - BG30_MagicItem_416 Token of the Old Gods — Spellcraft 法术是**两段
    定向选择链**（"Choose a minion. Then choose a minion from a Tier
    higher"），引擎 `needs_target` 只有单段; 且第二段候选域无权威
    （wiki 页无 Notes，patch 30.4.3→30.6.2 由 Discover 改为 choose）。
  - BG30_MagicItem_418 Bronzebeard Portrait — `GameTag.RACE` 单值，
    需多值种族身份（`RACES` 集合）。
  - BG30_MagicItem_431 Azerite Portrait — 载荷 `BG28_707` 未注册 +
    "Your Living Azerites **also** give stats" 是"改写另一张卡行为"的
    效果类别（RULES §7.4.6 例外条款：依赖 X 的行为）。
  - BG30_MagicItem_439 Designer Eyepatch — 三连阈值仅 hero 级单值
    （`GameTag.TRIPLE_THRESHOLD`），无按种族分档读取点。
  - BG30_MagicItem_440 Boom Controller — 战斗内**有界**"腾位补召"协议
    缺失（SOP §13 item 3 明令禁止 AFTER_ATTACK 无限补位）。
  - BG30_MagicItem_707 Tickatus Sticker — Darkmoon Prize 子系统缺失
    （RULES §11.4 已退役系统，无候选卡表 / 无 tier 映射数据）。
  - BG30_MagicItem_711 Marine Signet — "improve this" 的**档位递增**
    无数据字段、无官方权威（wiki 无 Notes; 无已注册先例——既有
    "improve this" 卡全部递增**属性值**）、越 T6 上限后的行为无定义。
  - BG30_MagicItem_777 Goose Portrait — ✅ 已迁出（2026-09-17，
    batch_goose_lucky_egg）: 载荷 `BG29_801`/`BG29_801_G` 已注册
    （batch_remaining2, 2026-09-16）、次生载荷 `BG30_104`/`_G` Lucky Egg
    由 batch_goose_lucky_egg 注册（"transform into" = 引擎 `Transform`
    + 金色 Tier 3/4 池化发现）→ 饰品本体同批注册。
  - BG30_MagicItem_803 Kaboom Bot Portrait — 载荷 `BG_BOT_606` /
    `TB_BaconUps_028` 已注册（batch_remaining2, 2026-09-16）; 残余:
    无"卡家族亡语伤害加成"读取点 + 金色口径无权威。
  - BG30_MagicItem_804 Ancient Wishbone — 引擎无"英雄技能效果触发两次"
    钩子（`extra_triggers` 只有 `hp_uses` = 每回合多次**使用**）。
  - BG30_MagicItem_821t2 Fishy Sticker — 金色 Fish of N'Zoth
    `TB_BaconUps_307` 无脚本（基础版 `TB_BaconShop_HP_105t` 已注册），
    且引擎无"金色定义 → 基础脚本回落"（ENGINE_BACKLOG §B15）。
  - BG30_MagicItem_822 Twin Sky Lanterns — 同 440（"when you have
    space" 战斗内腾位协议缺失，XML 无触发 tag、wiki 无 Notes）。
  - BG30_MagicItem_825 Smuggler Portrait — 载荷未注册 + "Your Whelp
    Smugglers **are Dragons**"是种族身份改写（无写-读点）。
  - BG30_MagicItem_828 Shaker Portrait — 载荷 `BG26_505` 已注册，但
    "give an extra copy" 需改 `ZestyShakerScript` 的私有记账
    （脚本侧重放会绕过其"每回合一次"闸——SOP §12 item 2 禁用）。

关联卡台账（RULES §7.4.6——关联卡自身脚本状态不阻塞本批 CORRECT，
除非本卡效果**依赖**该卡行为）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（`evolution_card_id` → `db.by_dbf`） | 脚本状态 |
  |------|--------------------------------------------|-----------|
  | BG30_MagicItem_548 | 126517 → BG34_Giant_035 Timewarped Glowscale | **未注册**
  |                    | （token, T5；其 Spellcraft 法术 126518 →         | （台账项——
  |                    | BG34_Giant_035t Timewarped Crown 亦未注册）      | 本卡效果不依赖它）
  | BG30_MagicItem_423 | 无（不交付卡牌）                                 | —
  | BG30_MagicItem_701 | 无（不交付卡牌）                                 | —
  本卡（548）第二条款的触发域是**任意** Spellcraft 法术（已注册的
  Spellcraft 源有 25 组: BG23_000/004/007/008、BG31_920/924、BG32_835、
  BG33_Reward_006、BG35_MagicItem_306/733/838/872、BG36_MagicItem_208、
  BG30_MagicItem_429/714 等），因此**不**满足 RULES §7.4.6 例外条款的
  "依赖被授予卡行为"（对照: 431/777/803/828 的点名条款依赖 X 的行为 →
  维持 DEFERRED）。同形已验收先例: Bassgill Portrait
  `BG32_MagicItem_301`（载荷 BG26_350 未迁移，对抗审查 VERIFIED_OK）。

接线审计读取点（W1/W2/W3 核对）
═══════════════════════════════════════════════════════════════════════
  饰品仅分发 `on_bind` / `start_of_turn` / `end_of_turn` /
  `start_of_combat`（W1 白名单）；本批只用 `on_bind`。监听事件全部有
  引擎生产点: `spell_resolved`（`Game._finish_play_spell` 每次施放
  结算后）、`minion_bought`（`Game.buy_from_tavern` 随从路径）、
  `spell_bought`（同函数法术路径）、`tavern_entity_added`
  （`Game.add_tavern_entity` 统一入馆入口）——`grep` 复核均有
  `fire(...)` 调用点（W2）。写入的 tag 全部有读取方（W3）:
  `TAVERN_EXTRA_TIER_SLOTS`（`refresh_tavern`）、
  `HEALTH_BUY`（`buy_from_tavern` 以生命代金分支）。
  **无** `game._x` 私有标记写入；随机零使用（本批无需随机）。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff
from hsrl2.events import (MINION_BOUGHT, SPELL_BOUGHT, SPELL_RESOLVED,
                          Listener)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
INNKEEPERS_STEIN = "BG30_MagicItem_423"      # Innkeeper's Stein (Lesser)
GLOWSCALE_PORTRAIT = "BG30_MagicItem_548"    # Glowscale Portrait (Greater)
EYE_OF_SARGERAS = "BG30_MagicItem_701"       # The Eye of Sargeras (Greater)

# DEFERRED（不注册；台账守卫见 test_batch_trinkets27.py）
CONDUCTOR_PORTRAIT = "BG30_MagicItem_402"
TOKEN_OF_THE_OLD_GODS = "BG30_MagicItem_416"
BRONZEBEARD_PORTRAIT = "BG30_MagicItem_418"
AZERITE_PORTRAIT = "BG30_MagicItem_431"
DESIGNER_EYEPATCH = "BG30_MagicItem_439"
BOOM_CONTROLLER = "BG30_MagicItem_440"
TICKATUS_STICKER = "BG30_MagicItem_707"
MARINE_SIGNET = "BG30_MagicItem_711"
GOOSE_PORTRAIT = "BG30_MagicItem_777"
KABOOM_BOT_PORTRAIT = "BG30_MagicItem_803"
ANCIENT_WISHBONE = "BG30_MagicItem_804"
FISHY_STICKER = "BG30_MagicItem_821t2"
TWIN_SKY_LANTERNS = "BG30_MagicItem_822"
SMUGGLER_PORTRAIT = "BG30_MagicItem_825"
SHAKER_PORTRAIT = "BG30_MagicItem_828"

# ── 关联卡 / 载荷 id（数据链 `evolution_card_id` → `CardDB.by_dbf`;
#    仅用于 docstring 台账与测试断言，脚本运行时一律经数据链解析） ──
TIMEWARPED_GLOWSCALE = "BG34_Giant_035"   # 126517（token, T5, Spellcraft）
TIMEWARPED_CROWN = "BG34_Giant_035t"      # 126518（其 Spellcraft 法术）
SNARLING_CONDUCTOR = "BG28_585"           # 402 载荷（未注册）
TOKEN_SPELL = "BG30_MagicItem_416t"       # 416 的 Spellcraft 法术（未注册）
LIVING_AZERITE = "BG28_707"               # 431 载荷（未注册）
SILVER_GOOSE = "BG29_801"                 # 777 载荷（已注册: remaining2）
LUCKY_EGG = "BG30_104"                    # 777 次生载荷（已注册:
                                          # goose_lucky_egg, 2026-09-17）
KABOOM_BOT = "BG_BOT_606"                 # 803 载荷（已注册: remaining2）
KABOOM_BOT_G = "TB_BaconUps_028"          # 803 金色载荷（已注册: remaining2）
FISH_OF_NZOTH_G = "TB_BaconUps_307"       # 821t2 金色载荷（未注册）
FISH_OF_NZOTH = "TB_BaconShop_HP_105t"    # 基础版（已注册——对照）
WHELP_SMUGGLER = "BG21_013"               # 825 载荷（未注册，race=NONE）
ZESTY_SHAKER = "BG26_505"                 # 828 载荷（已注册）


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


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


# ══════════════ BG30_MagicItem_423 Innkeeper's Stein ══════════════


class InnkeepersSteinScript:
    """
    Natural language: [x]The Tavern offers an extra minion of a higher
    Tier whenever it is <b>Refreshed</b>.

    Evidence: wiki.gg `Battlegrounds/Innkeeper's_Stein`（Lesser, cost 1,
    dbfId 111999）无 Notes 反证;"a higher Tier" = 高一档（印面无具体
    档位，数据无模板参数 num(0..3) 全 None → 无硬编码可能）。
    旧台账（batch_trinkets11 `InnkeepersSteinScript`）称"上界恒等于酒馆
    等级，无法让某一个额外展示位从 tier+1 抽取"——**已过期**:
    commit 66eaa35 落地展示位档位协议（`GameTag.TAVERN_EXTRA_TIER_SLOTS`
    + `TAVERN_EXTRA_TIER`，RULES §7.4.13），`refresh_tavern` 在常规
    抽取之外独立 `draw_tavern(extra_tier, extra_slots, min_tier=
    extra_tier)`。

    Formal spec:
      1. on_bind: hero 作用域 `TAVERN_EXTRA_TIER_SLOTS += 1`
          （**必写 hero 而非 game**——饰品不得污染对手酒馆，SOP §12
          item 9）。累加式（`.get(tag, 0) + 1`）使绑定前已存在的
          同 tag 来源（异变/其它饰品）不被覆盖（SOP §16b item 29）。
      2. **不写 `TAVERN_EXTRA_TIER`**: 引擎缺省 =
          `min(hero.tavern_tier + 1, game.max_tavern_tier)`，即"高一档
          且不越 T7 上限"。显式写入会把**绑定当刻**的 `tavern_tier + 1`
          冻结（酒馆等级随后升级 → 额外位档位错误），且在酒馆等级 6
          时绕过上限抽出 T7 随从。文本只说 "a higher Tier"，缺省即权威
          读法（RULES §7.4.13）。
      3. 之后**每次** `refresh_tavern`（手动 / 回合开始自动 / 任何调用
          方）都多出 1 个展示位，其抽取上下界均为 `extra_tier`——
          即恰好高一档; 该位与常规位共用同一条落馆路径
          （`minion_pool.acquire` 占池 → 金馆金色化 + `GILDED_NOT_
          TRIPPED` → `tavern_buffs` 持久面 → `tavern_entity_added`），
          故池占返/金馆/持久 Buff 自动正确。
      4. 常规位仍受上界 `hero.tavern_tier` 约束（额外位不改变常规位
          档位；与 `TAVERN_OFFER_TIER_EXACT` 无关）。
      5. 副本条款: 两份副本各 `+1` → 每次刷新多出 2 个高一档位
          （on_bind 各跑一次）。
      6. 落空/边界: 额外档位池空（该档可抽卡剩 0）→ `draw_tavern`
          自行抽不出（不抛错、不消耗额外资源）; 酒馆等级 = 上限档
          （标准局 6）→ 缺省封顶 `max_tavern_tier`，额外位仍存在
          （档位 = 上限档而非 T7）——引擎裁定，见 RULES §7.4.13。

    Test: test_batch_trinkets27.py — 绑定后 `refresh_tavern`:
      恰好多出 1 个 `tech_level == tavern_tier + 1` 的随从，其余全部
      `<= tavern_tier`（正对照: 同一 setup 无饰品 → 0 个越档随从）;
      owner 隔离（B 刷新仍全 `<= B.tavern_tier`）;
      池占返配平（`minion_pool` 可用总量 = 刷新前 − 本次抽取数，
      含额外位）; 金馆（`game._tavern_golden`）下额外位同样是金色本体
      + `GILDED_NOT_TRIPLED`; 跨回合持久（`end_recruit_phase` 后
      下一个招募回合的自动刷新仍有额外位）; 两份副本 → 多出 2 位;
      酒馆等级 5 → 额外位 T6; 同 seed 两次运行酒馆 card_id 序列一致

    Params: 无模板参数（BG30_MagicItem_423 num(0..3) 全 None——
            "a higher Tier" 由引擎缺省 tier+1 表达）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        h.set(GameTag.TAVERN_EXTRA_TIER_SLOTS,
              h.get(GameTag.TAVERN_EXTRA_TIER_SLOTS, 0) + 1)
        return None


# ══════════════ BG30_MagicItem_548 Glowscale Portrait ══════════════


class GlowscalePortraitScript:
    """
    Natural language: Get a Timewarped Glowscale. After you cast a
    <b>Spellcraft</b> spell, give your minions with <b>Divine Shield</b>
    +{0}/+{1}.

    Evidence: wiki.gg `Battlegrounds/Glowscale_Portrait`（Greater, cost 3,
    dbfId 112464; XML `BACON_EVOLUTION_CARD_ID=126517`,
    `TAG_SCRIPT_DATA_NUM_1=3`、`NUM_2=3`, `DIVINE_SHIELD=1`,
    `SPELLCRAFT-related`）——印面 +3/+3 与 `num(0)=num(1)=3` 一致
    （数据实读，非硬编码）; 页面无 Notes 反证。

    Formal spec:
      1. on_bind 第一条款: 数据链交付关联卡——`game.trinket_related_card
          (本饰品)`（`evolution_card_id=126517` → `BG34_Giant_035`
          Timewarped Glowscale，**token**、`is_pool_minion=False`）→
          `game.grant_trinket_related_card(hero, 本饰品)`:
          token → **零池操作**（RULES §2.3/§2.4）; 白板副本;
          满手 → `pending_hand_add` 入等待队列（RULES §3.3——不销毁）。
          交付落空（数据链断裂 / 卡定义非法）不影响第二条款:
          无论如何都注册监听（"Get a X" 的落空只作用于本次交付，
          不是整卡门槛）。
      2. on_bind 第二条款: 注册 `spell_resolved` **持久**监听
          （owner=饰品; 引擎在**每次施放效果结算后**广播——手牌路径
          `Game._finish_play_spell` 与效果施法 `cast_spell_effect` 同源，
          RULES §7.4.12）。**事件选择铁律**: 文本是 "**After** you cast
          a Spellcraft spell" → 必须用**后置** `spell_resolved`。
          用 `spell_resolving`（前置）会让本次施放自己吃到刚触发的
          加成（RULES §7.4.12 裁定: Honeycomb Ring 旧实现即因此
          把 improve 结算在触发法术之前）; 用 `spellcraft_cast` /
          `card_played` 则每次**打出**只广播一次，双施
          （`SPELL_DOUBLER` / `spellcraft_first` / `spell_first`）与
          效果施法全部漏算（RULES §7.4.10 / §16c item 36）。
      3. 命中条件: `spell.has(GameTag.SPELLCRAFT)`（Spellcraft 法术;
          法术塑造法术由 `spellcraft.generate_for_hero` 生成时打该 tag）
          ∧ `spell.controller is 绑定者`（"**you** cast"——对手施放
          不触发本人饰品; `_h=h` 默认参数绑定防闭包晚绑定，SOP §11.1）。
      4. 触发: 对绑定者棋盘上**全部存活且 `has(DIVINE_SHIELD)`** 的
          随从构造 `Buff(atk=num(0), health=num(1))`——**非 temporary**
          （文本无 "this combat"/"this turn" → 永久）。圣盾是**读取
          条件**不是授予物（本卡不赋予圣盾）。
      5. 落空: 本人无带圣盾的存活随从 → 本次不产生任何 Action
          （不消耗任何资源; 法术本身照常结算/消耗由引擎负责）;
          无关联卡数据链 → fail-loud 由 `grant_trinket_related_card`
          的 None 处理（不抛错）。
      6. 触发窗口在法术效果**之后**: 因此"本次施放刚给出圣盾"
          （如 Spellcraft 法术 `BG33_Reward_006t` Rushing Winds
          "Give a minion Windfury and Divine Shield"）的随从**会**
          吃到本次 +3/+3——这正是 `spell_resolved` 与 `spell_resolving`
          的行为分界（测试以该读法作证伪探针）。
      7. 副本条款: 两份副本各有独立 on_bind + 监听 → 每次施放各给
          一份 num(0)/num(1)（叠加）; 数据链交付各自占一套（token
          零池操作，故无池耗尽问题）。

    Test: test_batch_trinkets27.py — 绑定后手牌出现
      `BG34_Giant_035`（token → 随从池总量不变; 正对照: 无饰品手牌
      不变）; 真实 `play_spell` 施放带 SPELLCRAFT tag 的法术后
      本人**带圣盾**随从 +num(0)/+num(1) 且**不带圣盾**随从不变
      （正负对照同方法）; **后置语义证伪探针**: 以 `BG33_Reward_006t`
      （Rushing Winds，效果是给目标圣盾）为目标施放 → 目标**本次**
      即吃到 +3/+3（若实现误用 `spell_resolving` 则不成立）;
      无圣盾随从在场时施放普通 Spellcraft 法术 → 无属性变化;
      施放**非** Spellcraft 法术（池法术）不触发;
      对手施放 Spellcraft 不触发（owner 隔离）;
      双施（棋盘 `SPELL_DOUBLER`）按**施放次数**结算两次;
      满手绑定 → 副本进 `pending_hand_queue`（不丢失）;
      跨招募回合（真实 `end_recruit_phase`）后监听仍生效;
      两份副本 → 每次施放两份叠加

    Params: {0}=num(0)=3 {1}=num(1)=3（BG30_MagicItem_548，
            数据实读 `data/bg_trinkets.json`）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # 第一条款: 数据链交付关联卡（token → 零池操作; 满手入等待队列）
        game.grant_trinket_related_card(h, source.card_id)
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def on_resolved(g, spell=None, _h=h, **kw):
            if spell is None or spell.controller is not _h:
                return
            if not spell.has(GameTag.SPELLCRAFT):
                return
            targets = [m for m in _living(_h)
                       if m.has(GameTag.DIVINE_SHIELD)]
            if not targets:
                return
            g.run_actions([Buff(m, atk=atk, health=health)
                           for m in targets])

        game.events.register(Listener(
            event=SPELL_RESOLVED, owner=source, callback=on_resolved))
        return None


# ══════════════ BG30_MagicItem_701 The Eye of Sargeras ══════════════


class EyeOfSargerasScript:
    """
    Natural language: [x]Every fourth card you buy costs Health instead
    of Gold. <i>({0} left!)</i>@[x]Every fourth card you buy costs
    Health instead of Gold. <i>(Ready!)</i>

    Evidence: wiki.gg `Battlegrounds/The_Eye_of_Sargeras`（Greater,
    cost 5, dbfId 117795; XML `TAG_SCRIPT_DATA_NUM_1=3`,
    `BACON_TRIGGER_XY=1`, `BACON_SUBSET_DEMON=1`）; 页 Notes 仅有
    提供门禁（"没有回血卡的玩家不会被提供本饰品"——属未实现的
    RULES §7.4.2 提供规则子系统，非本卡效果），无措辞歧义反证。
    `num(0)=3` = 印面 "({0} left!)" 的起始计数。旧台账
    （batch_trinkets12）称"引擎只有 CardDef 静态 `health_cost`，无
    '按购买次数切换支付方式'的运行时标记与消费点"——**已过期**:
    commit 690ded8 落地以生命代金购买协议（RULES §7.4.7），其**来源 2**
    正是"给**当前酒馆中**的实体打实体级 `GameTag.HEALTH_BUY`，
    `buy_from_tavern` 统一判定并在成交时消费"。

    Formal spec:
      1. on_bind: 滚动计数（监听闭包内 `{"n": int}`，per-copy 独立）
          本人**买入的卡**。事件域 = 全部真实购买生产点:
          `minion_bought`（`Game.buy_from_tavern` 随从路径,
          载荷只有 `minion=` → 用 `minion.controller is 绑定者` 过滤）
          + `spell_bought`（同函数法术路径, 载荷 `hero=`）。
          "card you buy" 不含饰品购买（`trinket_bought` 是另一语义）
          与效果生成的卡（非购买）。
      2. **武装**（第 `num(0) - 1` 张买入后）: 给绑定者酒馆内**全部**
          实体（随从 + 法术）打实体级 `HEALTH_BUY`——于是"第 num(0) 张
          卡"成交时 `buy_from_tavern` 走以生命代金分支
          （`cost > 0 and entity.get(HEALTH_BUY)`），支付金额 =
          该次报价的金币价（折扣/覆盖后），护甲先扣; 生命+护甲不足以
          支付 → 购买失败（返回 False）且**不消费**标记。
          同时注册 `tavern_entity_added` 持久监听（RULES §7.4.9 唯一
          入馆入口，含 turn 开始自动刷新/Fodder 注入/脚本换卡）:
          武装期内新入馆的实体补标——因此"武装后先刷新再买第四张"
          同样正确（顺序无关，SOP §16c item 38 纪律）。
      3. **解除武装**（第 num(0) 张买入后）: 计数归零并清除**本次自己
          打过**的标记（闭包维护的 uuid 集）——**只清自己打的**，
          不碰其它来源（如 `BG35_MagicItem_152`）在同一实体上设的
          `HEALTH_BUY`（SOP §16b item 28/29: 多来源共用状态不得互相
          覆盖）。随后滚动重来。
      4. 计数**跨回合累积**（文本无 "this turn"）: 回合边界不清零;
          回合开始的自动刷新由第 2 条的 `tavern_entity_added` 覆盖。
          绑定当刻之前已买的卡不可见（引擎无购买历史读取点）——
          精度缺口与 `BG30_MagicItem_992` 同族（RULES §7.4.13 口径），
          不构成近似实现（绑定后行为完全精确）。
      5. 生命支付后 **不**回血、**不**改金币; 金币不足但生命足够时
          仍按生命支付（"instead of Gold" 是强制替换——RULES §7.4.7）。
      6. 落空: 武装期标记的实体全部离馆（被对手清空酒馆类效果）→
          下一次购买按金币结算、计数继续累积; 无候选时无副作用。
      7. 副本条款: 两份副本各有独立计数器 → 两者在同一批购买序列上
          同时武装/解除，效果**不叠加**（第 num(0) 张仍只支付一次
          生命）——测试断言"每 num(0) 张恰好一次"。

    Test: test_batch_trinkets27.py — 绑定后从酒馆真实
      `buy_from_tavern` 买 4 张: 第 1–3 张扣金币（正对照），第 4 张
      **金币不变、生命 −= 该卡金币价**且卡仍入手; 第 5 张回到金币
      （解除武装 — 断言剩余馆内实体不再带 `HEALTH_BUY`）;
      跨回合: 回合 1 买 2 张 + `end_recruit_phase` → 回合 2 再买 1 张
      后武装，第 4 张（回合 2）支付生命（含自动刷新后的新实体）;
      生命不足 → `buy_from_tavern` 返回 False、金币/生命均不变、
      标记保留（随后足量时仍支付生命 = 落空不消耗）;
      法术购买同样计入（第 4 张为酒馆法术 → 生命支付）;
      对手购买不计入本人计数、且对手酒馆实体无 `HEALTH_BUY`
      （owner 隔离）; 另一来源预先设的 `HEALTH_BUY` 在本人解除武装后
      仍在（不覆盖其它来源）; 两份副本 → 每 4 张恰好一次生命支付

    Params: {0}=num(0)=3（BG30_MagicItem_701，数据实读）；
            "Every fourth card" = `num(0) + 1` 张（印面计数从 3 起
            倒数 → 第 4 张触发）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0) + 1   # "fourth"
        state = {"n": 0, "armed": False, "marked": set()}

        def _mark(entity):
            """只给**当前没有标记**的实体的打标并记账（不清他人标记）。"""
            if not entity.get(GameTag.HEALTH_BUY, False):
                entity.set(GameTag.HEALTH_BUY, True)
                state["marked"].add(entity.uuid)

        def _arm():
            state["armed"] = True
            for e in list(h.tavern):
                _mark(e)

        def _disarm():
            state["armed"] = False
            for e in list(h.tavern):
                if e.uuid in state["marked"]:
                    e.clear(GameTag.HEALTH_BUY)
            state["marked"].clear()

        def _tick():
            state["n"] += 1
            if state["n"] >= threshold:
                state["n"] = 0
                _disarm()
            elif state["n"] == threshold - 1:
                _arm()

        def on_minion_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            _tick()

        def on_spell_bought(g, hero=None, **kw):
            if hero is not h:
                return
            _tick()

        def on_tavern_added(g, hero=None, entity=None, **kw):
            if hero is not h or entity is None:
                return
            if state["armed"]:
                _mark(entity)

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=source, callback=on_minion_bought))
        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=source, callback=on_spell_bought))
        game.events.register(Listener(
            event="tavern_entity_added", owner=source,
            callback=on_tavern_added))
        return None


# ══════════════ DEFERRED（不注册；逐张 Status/Dependency/Path） ══════


class ConductorPortraitScript:
    """
    Natural language: [x]Get a Snarling Conductor. Whenever you discard
    a card, this plays a <b>Blood Gem</b> on all your minions.

    Status: DEFERRED — requires 弃牌系统（`CARD_DISCARDED` +
      `game.discard_card`）

    Dependency:
      1. 引擎**零弃牌机制**: `grep -rn "discard" hsrl2/`（排除
         `__pycache__`）只命中 `set.discard` / `_death_processing.discard`
         / 测试注释——无 `discard_card` 入口、无任何弃牌事件常量
         （`hsrl2/events.py` 无 `CARD_DISCARDED`）、无"选择一张手牌丢弃"
         的选择器协议。两处挂载点（`SnarlingConductorScript` 本体与
         本饰品的 "Whenever you discard a card"）因此都是死监听
         （SOP §16b item 26）。
      2. 载荷 `BG28_585` Snarling Conductor（"At the start of your turn,
         discard a spell to gain 4 Gold."，`is_pool_minion=False`）
         **未注册**（`REGISTRY` 运行核验无 id）——即使补弃牌机制，
         第一条款交付的卡仍是空转。
      3. "this plays a Blood Gem on all your minions" 的施加者语义
         （饰品实体非随从、鲜血宝石供应者是饰品还是英雄）无权威;
         已注册的同族"play Blood Gems on all friendly minions"
         （`BG32_MagicItem_274` Bristlebach Portrait 族）走的是
         `PlayBloodGems` 统一出口——弃牌机制落地后按该出口实现。
    Implementation path: (a) 引擎补 `events.CARD_DISCARDED` +
       `game.discard_card(hero, entity)`（手牌移除 + 广播 + 可带
       `reason=`）与"由卡效果选择弃牌"的 `PendingChoice` 协议;
       (b) 迁移 `BG28_585`/`BG28_585_G`（Sot 弃牌换金）;
       (c) 本卡 on_bind = 交付关联卡 + 注册 `CARD_DISCARDED`
       （`hero is 绑定者`）→ `PlayBloodGems(hero, count=1,
       target=hero.board 全体)`。阻塞卡: BG30_MagicItem_402 +
       BG28_585。
    Reference: `docs/agents/ENGINE_BACKLOG.md` §B12;
      `batch_trinkets11.ConductorPortraitScript` 原台账（本批复核维持）。

    Test: 不注册（DEFERRED）——台账守卫见
      test_batch_trinkets27.py::TestRegistryLedger。

    Params: 无模板参数（BG30_MagicItem_402 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TokenOfTheOldGodsScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Choose a minion. Then choose
    a minion from a Tier higher to transform it into.

    Status: DEFERRED — requires 两段定向选择链（法术的
      `target_count` 链 / 第二段候选域协议）

    Dependency:
      1. 关联法术 `BG30_MagicItem_416t`（"Choose a minion. Then choose a
         minion from a Tier higher to transform it into."，
         `spellcraft_id=112813` 数据核实）**未注册**，且其效果是
         **两段**玩家选择: 第一段"Choose a minion"（**非** friendly——
         文本无 "friendly"，候选域含敌方随从），第二段"choose a minion
         from a Tier higher"（更高一档）。引擎的定向法术协议
         （`needs_target` → `PendingChoice(kind="spell_target")`，
         `Game.play_spell`）只有**单段**目标; `target_count=2` 是
         **英雄技能**专用链（`Game.use_hero_power` 的 `_chain`），
         法术路径无该读取点。
      2. 第二段的候选域无权威: wiki 页
         `Battlegrounds/Token_of_the_Old_Gods`（2026-09-14 复读）**无
         Notes 段**; 仅记录措辞沿革——30.4.3 版 "**Discover** a minion
         from a Tier higher"、30.6.2 版改为 "choose a minion from a Tier
         higher"，而 patch 注释未说明候选来自**池** / **酒馆** /
         **棋盘**（"Discover" 版暗示池 + 三选一，但现行文本已去掉
         Discover，候选数与域都无从确定）。SOP §6b 第 4 步: 查无证据
         → DEFERRED（宁缺毋错）。
      3. 第一段目标域含**敌方**随从 → 需要自定义 `target_candidates`
         （默认全体友方存活随从），而"choose a minion"是否含敌方随从
         亦无 Notes 明文（同为第 2 条的留档项）。
    Implementation path: (a) 引擎把 `target_count` 链推广到法术路径
      （`play_spell` 复用 `use_hero_power` 的 `_chain` 模式，逐段
      `PendingChoice` + 每段独立 `target_candidates`），或新增
      "两段选择法术"协议（第一段选定后由脚本经 affordance 推入第二段
      `PendingChoice`，`resolve_callback` 里调 `Transform`）;
      (b) 取得第二段候选域权威（池？酒馆？+ 是否受池剩余约束）;
      (c) 迁移 `BG30_MagicItem_416t`（`Transform(target, new_id)` +
      池占返由 Transform 既有协议处理，RULES §6.21）+ 本饰品 on_bind
      （饰品版 Spellcraft 生成点已就绪: `spellcraft.generate_for_hero`
      遍历 `hero.trinkets`，见 batch_trinkets11 429 先例——本卡唯一
      缺口是法术脚本自身）。阻塞卡: BG30_MagicItem_416 +
      BG30_MagicItem_416t。
    Reference: `batch_trinkets11.TokenOfTheOldGodsScript` 原台账
      （其"饰品版 Spellcraft 生成点缺失"部分已由 429 解冻时补齐;
      剩余缺口 = 两段选择链 + 第二段候选域权威）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_416 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BronzebeardPortraitScript:
    """
    Natural language: [x]Get a Brann Bronzebeard and a random
    <b>Battlecry</b> minion. Your Brann Bronzebeards are both Murlocs
    and Dragons.

    Status: DEFERRED — requires 多值种族身份（`RACES` 集合 / 双种族）

    Dependency:
      1. 第二条款"are **both** Murlocs and Dragons"需要**同时**属于两个
         种族的身份。引擎 `GameTag.RACE` 是**单值** tag
         （`Minion.race` / `_KEYWORD_TAG_MAP` / `race_auras` 全部按
         单值比较），`Race.ALL` 的语义是"匹配一切种族"（
         `race in (X, Race.ALL)` 双向匹配），把它写给 Brann 会让它
         被野兽/机械/…所有种族光环命中——语义完全不同（多语言文本为
         "既是鱼人也是龙"，非"全种族"）。
      2. 第一条款本身可交付（`BG_LOE_077` Brann Bronzebeard 是
         **池随从**且脚本已注册; "a random Battlecry minion" 走
         `GetRandomMinion` + `BATTLECRY` 过滤），但二态铁律不允许
         "半实现"（SOP §6b）。
    Implementation path: 引擎新增多值种族身份——`GameTag.RACES`
      （frozenset 或位掩码）+ `Minion.race` 改为集合视图（保留单值
      兼容读取 `race`）+ 全部 `race` 读取点改造（
      `_tavern_race` / `race_auras` / `ApplyRaceAura` / `_health_buy_
      race_matches` / `_type_association` / Discover 种族过滤）;
      随后本卡 on_bind = 交付 Brann + `GetRandomMinion(关键字=BATTLECRY)`
      （占池/满手排队）+ 对本人棋盘与后续入场的 Brann 家族写
      `RACES = {MURLOC, DRAGON}`（家族 = 本体 + `golden_version`）。
      同缺口阻塞: `BG30_MagicItem_971` Enforcer Portrait /
      `BG32_MagicItem_179` Drakkari Portrait / `BG32_MagicItem_825`
      Smuggler Portrait。阻塞卡: BG30_MagicItem_418。
    Reference: `docs/agents/ENGINE_BACKLOG.md` §A1/§B2-4;
      `batch_trinkets8` / `batch_trinkets11` 同卡台账（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_418 num(0..3) 全 None；
            数据链 96786 → BG_LOE_077）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class AzeritePortraitScript:
    """
    Natural language: [x]Get a Living Azerite. Your Living Azerites
    also give stats to friendly Elementals.

    Status: DEFERRED — requires 载荷脚本 + "按卡家族追加效果"读取点
      （RULES §7.4.6 例外条款: 本卡效果**依赖**被授予卡的行为）

    Dependency:
      1. 载荷 `BG28_707` Living Azerite（"Whenever you cast a Tavern
         spell, give Elementals in the Tavern +{0}/+{1} this game."，
         `is_pool_minion=False`、T5）**未注册**; 其金色 `BG28_707_G`
         同样未注册——交付的 Living Azerite 是白板，"also give stats
         to friendly Elementals"没有任何被改写的对象。
      2. "**also** give stats to friendly Elementals"是**改写另一张卡
         脚本行为**的效果类别: 引擎无"按 card_id 家族给某张卡追加一段
         效果"的协议（`Entity.set_script_override` 只作用于**已存在
         实体**，无法覆盖之后获得的副本，也无法按 owner 限定），
         且不能由本饰品自行监听 `tavern_spell_cast` 重放（那会与
         Living Azerite 本体脚本的 `this game` 累积口径重复计数，
         SOP §12 item 14 载荷数值权威）。
      3. 与 `racefx.elemental_give_bonus`（元素 **give-stats 给予者**
         的加成出口）无关: 该出口作用于"给予者是元素"的卡自身数值，
         本卡要改的是 **Living Azerite 的给予对象集**（从"酒馆元素"
         扩到"友方元素"），是另一维度。
    Implementation path: (a) 迁移 `BG28_707`/`BG28_707_G`
      （`tavern_spell_cast` 监听 + 酒馆元素 `this game` 累积 Buff，
      需 hero 级来源计数）; (b) 引擎新增"owner 级卡家族追加效果"读取
      点（如 `hero.card_family_mods[family_key] = fn`），本体脚本在
      构造 Buff 目标集时求值（生命周期校验来源仍在 `hero.trinkets`）;
      随后本卡 on_bind = 交付关联卡 + 注册该追加面。阻塞卡:
      BG30_MagicItem_431 + BG28_707。
    Reference: `batch_trinkets11.AzeritePortraitScript` 原台账
      （本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_431 num(0..3) 全 None；
            数据链 107939 → BG28_707）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class DesignerEyepatchScript:
    """
    Natural language: You only need 2 copies of a Pirate to make it
    Golden.

    Status: DEFERRED — requires 按种族分档的三连阈值

    Dependency:
      1. 三连阈值是 **hero 级单值** `hero.get(GameTag.TRIPLE_THRESHOLD,
         3)`，唯一读取点 `Game.check_for_triple`（`hsrl2/game.py`）。
         把它设成 2 会让**所有**种族都只需 2 份（Clocksworth 的
         "全域双份"口径），与文本的"**Pirate**"限定不符; 不设 = 无效果。
      2. `check_for_triple` 的候选集是"同名 card_id"（手牌 + 棋盘 +
         替代三连 BG26_175），没有任何按 `db.get(acquired.card_id).race`
         取阈值的分支。
      3. Amalgam（`Race.ALL`）是否算 Pirate、金色副本是否参与计数
         两点需与阈值改造一并裁定（RULES §10.1 记档）。
    Implementation path: 引擎新增 `hero.triple_threshold_by_race`
      （race → N，与 `TRIPLE_THRESHOLD` 累加/取小）+
      `check_for_triple` 按基础卡定义的 `race`（含 `Race.ALL` 匹配规则，
      RULES §6.18）选阈值; 随后本卡 on_bind 写
      `{Race.PIRATE: 2}`（"2 copies" 为文本字面量——CardDef num 全
      None，按 SOP §3 在 Params 声明）。阻塞卡: BG30_MagicItem_439。
    Reference: `batch_trinkets5` / `batch_trinkets11` 同卡台账
      （本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（"2 copies" 为文本字面量; num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BoomControllerScript:
    """
    Natural language: [x]When you have space, summon an exact copy of
    your first Mech that died each combat.

    Status: DEFERRED — requires **有界**的"战斗内腾位补召"协议

    Dependency:
      1. 该卡 XML 权威标签只有 `START_OF_COMBAT=1`（dbf 113095，
         wiki XML tags 同），但 "your first Mech that **died each
         combat**" 指向战斗内**持续**触发——SoC 时点本场尚无死亡
         （`game.combat_death_log` 在 `run_combat` 开头清空），
         SoC 单检查点必然空转（注册即 no-op = 禁止的第三态）。
      2. 直译为 AFTER_ATTACK 循环补位正是主线在 SOP §13 item 3 明令
         禁止的形态（Drek'Thar/Ozumat "死一只→补一只"曾致 2001 轮
         `CombatLoopError`）; `combat_summon_log` 只写不读（W3 空转）。
      3. "exact copy"的**精确副本**语义（含 buff / 金色 / 亡语栈——
         Zerek / `_exact_copy` 口径）与"first Mech"的本场首死快照
         （死亡时属性 vs 入场时属性）都需一并裁定。
    Implementation path: 主线先裁定该族的**有界**触发协议（每场次数
      上限 + 与攻击循环的终止性证明，并写入 RULES §3.x），再在
      `DEATH` 处理链上登记"本场首个机械"的 `(card_id, golden,
      snapshot_state)`，于有界腾位检查点
      `create_minion + restore_state + summon`。阻塞卡:
      BG30_MagicItem_440 + BG30_MagicItem_822（同族）。
    Reference: `batch_trinkets11.BoomControllerScript` 原台账
      （本批复核维持）; `docs/agents/ENGINE_BACKLOG.md` §B14。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（`script_data_num_2=99` 为内部计数参数，
            非文本占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TickatusStickerScript:
    """
    Natural language: [x]<b>Discover</b> a Tier 3 Darkmoon Prize. At the
    start of every three turns, repeat this. <i>({0} |4(turn, turns)
    left!)</i>

    Status: DEFERRED — requires Darkmoon Prize 卡池定义 + 档位映射

    Dependency:
      1. Darkmoon Prize 子系统在数据层**不存在**: `data/bg_cards.json`
         中无任何"Tier 3 Darkmoon Prize"候选集——`BGS_Treasures_*`
         （Big Banana / Pocket Change / Gacha Gift / Evolving Tavern /
         Might of Stormwind …）是 **Battlegrounds 奖品（Season 4/5）**
         且**无任何 tier 字段**（`tech_level` 恒 0），与 Darkmoon Prize
         不是一个集合; 名字含 "Prize" 的 7 张（`BG27_Anomaly_Prizes2`
         异变 / `BG31_Anomaly_115t` Magic Prize / `BG35_MagicItem_812t`
         Triple Prize / `TB_BaconShop_HP_101t2` / `TB_BaconShop_HP_106`
         Prize Wall / `BG21_014` Prized Promo-Drake）全部与本卡无关。
      2. RULES §11.4 已把 Darkmoon Prizes 记为"已退役的季节性系统，
         某些异常规则下可能回归"——无候选表、无 tier 映射、无
         "发现一张 Prize 法术并结算"的协议（Discover 只服务卡池
         随从/法术/奖励）。
      3. "At the start of every three turns, repeat this" 的周期与
         `num(0)=3` 的 `({0} turns left!)` 计数语义（每 3 回合一次
         vs 首次即时）需与 Prize 候选一并裁定。
    Implementation path: 先由数据/官方补全 Darkmoon Prize 候选集与其
      Tier 映射（生成器导出奖项表的 tier 字段），再复用
      `Discover(hero, candidates=该 tier 的 Prize)`（引擎预留语义）
      + 三回合周期计数（首次 on_bind 即时 + 每 3 个 `start_of_turn`
      重复）。阻塞卡: BG30_MagicItem_707（+ 同族 Prize 消费卡）。
    Reference: `docs/agents/ENGINE_BACKLOG.md` §B2-11 / RULES §11.4;
      `batch_trinkets12.TickatusStickerScript` 原台账（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=3（BG30_MagicItem_707）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class MarineSignetScript:
    """
    Natural language: [x]After you play 4 minions, get a random Tier {1}
    Tavern spell and improve this. <i>({0} left!)</i>

    Status: DEFERRED — requires "improve this" 对**档位**的增量权威
      （含上限行为）

    Dependency:
      1. 本卡可改善的量只有**档位** `{1}`（`num(1)=1` 为初始档位）:
         文本 "improve this" 的**增量**在数据中**无字段**
         （`num(0)=4` 是"play 4 minions"阈值、`num(1)=1` 是初始
         Tier，`num(2/3)` 为 None; XML 亦无 NUM_3/4 相关值）——按
         "+1" 实现属**文字推断**而非数据权威。既有已注册的
         "improve this" 卡（`BG32_MagicItem_200/232/280/700/801/922`、
         `BG35_MagicItem_300/701`、`BG36_MagicItem_380`）**全部**递增
         **属性值**且增量 = 印面 `num(i)`; 没有任何已验收先例递增
         **Tier**（ENGINE_BACKLOG §C 的"递增步长口径（印面值 vs
         固定 +1）"留档正是指该族，全仓不一致）。
      2. wiki 页 `Battlegrounds/Marine_Signet`（2026-09-14 复读）
         **无 Notes 段**，仅记录 patch 34.2 把 "upgrade this" 改为
         "improve this"; 未说明增量与上限。
      3. **上限行为无定义**: 酒馆法术只有 T1–T6（RULES §3.6.1 per-tier
         副本模型）; 档位提升到 7 以后"get a random Tier 7 Tavern
         spell"的落空/封顶/停升三种读法都无权威。
      4. 数据第二状态文本（`@` 后）为 "After you play 4 minions, get
         a random Tier {1} Tavern spell."——**去掉了** "and improve
         this"，与"计数复位后继续改善"的读法存在文本张力，进一步
         需要权威（SOP §6b 第 2 步）。
    Implementation path: 取得官方/实测权威（增量 = +1 还是其它、
      上限封顶在最高法术档还是继续计数但落空、第二状态文本的含义）
      后: on_bind 注册 `card_played`（本人 `Minion` 计数，rolling
      `num(0)` 复位——"play" 域见 RULES §7.4.10）+ 状态
      `{"tier": num(1)}`; 满足时从 `db.pool_spells()` ∩
      `spell_pool.available > 0` ∩ `tech_level == 当前档位` 随机取
      （`game.rng`）→ `spell_pool.acquire` + `pending_hand_add`
      （占池/满手排队 RULES §2.3/§3.3）; 无候选 → 落空不消耗额度;
      随后按权威递增档位。阻塞卡: BG30_MagicItem_711。
    Reference: `batch_trinkets12.MarineSignetScript` 原台账
      （本批复核维持——"improve this 的数值/文本升级协议"仍缺）;
      RULES §7.4.8 / ENGINE_BACKLOG §C。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=4（计数阈值） {1}=num(1)=1（初始档位）
            "improve" 的增量与上限**无数据通道**（见 Dependency 1/3）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# 777 Goose Portrait 已由 batch_goose_lucky_egg 注册（2026-09-17）→
# 占位 DEFERRED 类删除（迁移轨迹见本模块 docstring DEFERRED 清单与
# test_batch_trinkets27 的 `DEFERRED_IDS` 注记）。


class KaboomBotPortraitScript:
    """
    Natural language: [x]Get a Kaboom Bot. Your Kaboom Bots'
    <b>Deathrattles</b> deal 10 extra damage.

    Status: ✅ **已迁出 → batch_trinkets39**（2026-09-18）。

    迁移依据（owner 权威序）: 原剩余阻塞 = 金色 "twice" 下 10 点是
    **每实例 +10 还是总额 +10** 无权威。复核确认
    hearthstone.wiki.gg/Battlegrounds/Kaboom_Bot_Portrait
    （oldid=921183）**无 Notes 段** → 按卡面天然语言裁定**逐实例 +10**
    （每实例 4+10=14; 金色 14+14）; 否决"总额 +10 一次"（= 4+4+10 = 18
    无法在两条各自独立选取目标的伤害实例间分配，文本无 "split"）。
    读取点: RULES §7.4.16 `hero.family_flags` +
    `Game.add_family_flag` / `family_flag`（Bristlebach 先例）; 载荷
    `batch_remaining2.KaboomBotScript.deathrattle` 读
    `FLAG_KABOOM_DR_BONUS` 并把 `KABOOM_EXTRA_DAMAGE`(=10) 传给
    `KaboomBlast`。完整推导与边界见 `batch_remaining2.KaboomBotScript`
    docstring §6–8。
    Reference: `batch_trinkets12.KaboomBotPortraitScript` 原台账;
    `batch_trinkets34` Bristlebach Portrait §7.4.16 先例。

    Test: 已实现——见 `hsrl2/tests/test_batch_trinkets39.py`。

    Params: 无模板参数（"10 extra damage" 为文本字面量，声明在载荷侧
            `KABOOM_EXTRA_DAMAGE`; BG30_MagicItem_803 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class AncientWishboneScript:
    """
    Natural language: Your Hero Power triggers twice.

    Status: DEFERRED — requires 英雄技能**效果结算翻倍**钩子

    Dependency:
      1. `Game.use_hero_power` / `_finish_hero_power` 只支持"每回合可用
         **次数**"（`uses_per_turn` + `hero.extra_triggers["hp_uses"]`，
         RULES §6.20——Sous Chef Sticker 的"an extra time each turn"），
         **没有**"单次使用效果结算两次"的读取点: 脚本钩子
         `script.hero_power(hero, self, ctx)` 只被调用一次。
      2. 用 `hero_power_used` 监听在饰品侧重放效果被 SOP §15 明令
         禁止（"禁止在卡脚本里自己写计数器重放效果"），且技术上不可行:
         事件载荷不含本次使用的 `target`（定向技能无法重放）、
         `passive=True` 的技能根本没有 hero_power 钩子、
         重放还会绕过技能的每回合/每局计数语义。
      3. 该效果是否也翻倍**被动**技能与技能费用无权威（多语言文本
         只写 "triggers twice"）。
    Implementation path: 引擎新增独立配额（而非复用 `hp_uses`）:
      `hero.extra_triggers["hp_times"] = 1` 在
      `_finish_hero_power` 的脚本调用处消费——形如
      `for _ in range(1 + hero.extra_trigger("hp_times")): script.
      hero_power(...)`（与 `_finish_play_spell` 的 `spells` 循环同构，
      按 cast 结算、计数只记一次、费用只扣一次）; 随后本卡 on_bind
      写 `hp_times += 1`。阻塞卡: BG30_MagicItem_804（+ 同族
      "Hero Power triggers twice" 卡）。
    Reference: `batch_trinkets7` / `batch_trinkets8` /
      `batch_trinkets12` 同卡台账（本批复核维持）; RULES §6.20。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_804 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class FishyStickerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Summon a Golden Fish of
    N'Zoth that copies <b>Deathrattles</b>.

    Status: DEFERRED — requires 金色定义 → 基础脚本回落（引擎级）

    Dependency:
      1. 关联卡数据链 `evolution_card_id=67216` → `TB_BaconUps_307`
         **金色 Fish of N'Zoth**（`is_pool_minion=False`，文本
         "After a different friendly **Deathrattle** minion dies in
         combat, gain its **Deathrattle** twice."）——该金色 id
         **无脚本**（`REGISTRY` 运行核验无 id）。
      2. 基础版 `TB_BaconShop_HP_105t` Fish of N'Zoth **已注册**
         （`batch_hero_econ3.FishOfNZothScript`: `on_summon` 登记
         `_gained_drs` + `deathrattle` 重放）。但
         `Game.create_minion(card_id, golden=True)` 会把 `card_id`
         解析成**金色独立定义**并按该 id 绑定脚本 →
         `REGISTRY.get("TB_BaconUps_307")` 为 None →
         召唤出的金色鱼是**白板**（on_summon 不跑、亡语不重放），
         本饰品效果整体落空（注册即 no-op = 禁止的第三态）。
      3. 引擎**无**"金色卡定义存在但无脚本 → 显式回落到基础卡脚本"
         的协议（ENGINE_BACKLOG §B15 列为待实现，且明确要求
         "需显式审计，不能静默"）。饰品脚本侧手动
         `fish.scripts = <基础脚本类>` 属跨批次私有耦合 + 绕过引擎
         审计（禁止的近似实现）。
    Implementation path: 引擎在 `create_minion` / `create_entity` 的
      脚本绑定处增加**显式审计**的金色回落（金色 def 的
      `triple_base_id` → 基础 def 的 REGISTRY 脚本，命中时记
      `dark_gift_audit_log`），并补"金色 Fish of N'Zoth 的
      `deathrattle` 重放两次"的**金色行为差异**表达（金色文本
      "gain its Deathrattle **twice**"——基础脚本需按 `is_golden`
      分支或在金色回落时读取金色 CardDef 文本）; 随后本卡 on_bind =
      SoC 钩子: `create_minion(基础 id, golden=True)` + `summon`
      （战斗级召唤不占池——`Summon` 语义，RULES §2.3 "效果召唤的
      临时体不占池"）。阻塞卡: BG30_MagicItem_821t2（+ 全部
      "金色定义无脚本"族）。
    Reference: `docs/agents/ENGINE_BACKLOG.md` §B15;
      `batch_trinkets12.FishyStickerScript` 原台账（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_821t2 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TwinSkyLanternsScript:
    """
    Natural language: [x]When you have space, summon a copy of the
    first minion you summon each combat.

    Status: DEFERRED — requires 战斗内"腾位"触发协议 + 本战斗首个召唤记录

    Dependency:
      1. 本卡 XML 无任何触发 tag（仅 `TRIGGER_VISUAL`; `script_data_
         num_2=1` 为内部参数），wiki 页无 Notes 段 → "when you have
         space" 的**触发时点**（每次攻击后？每个死亡结算后？每当棋盘
         出现空位？）无权威。
      2. 引擎侧 `combat_summon_log` 只写不读（W3 空转标记），且无
         "棋盘腾位"事件/检查点; 直译为 AFTER_ATTACK 补位正是
         SOP §13 item 3 明令禁止的形态（同类文本曾致 2001 轮
         `CombatLoopError`）——必须由主线先给出**有界**协议与终止性
         证明。
      3. "a copy of the first minion **you** summon each combat"需要
         战斗内首个召唤物的**快照**（card_id + 当前属性 + buff?）——
         "copy" 是白板副本还是精确副本无权威。
    Implementation path: 同 `BoomControllerScript`（440）: 主线裁定
      有界腾位协议 + 本场首个召唤记录（`run_combat` 内 per-hero
      首个 `summon` 快照），随后本卡 SoC/监听实现。阻塞卡:
      BG30_MagicItem_822 + BG30_MagicItem_440（同族）。
    Reference: `docs/agents/ENGINE_BACKLOG.md` §B14;
      `batch_trinkets12.TwinSkyLanternsScript` 原台账（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（`script_data_num_2=1` 为内部计数参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class SmugglerPortraitScript:
    """
    Natural language: [x]Get a Whelp Smuggler. Set its stats to 12/12.
    Your Whelp Smugglers are Dragons.

    Status: DEFERRED — requires 单值种族**身份改写**协议
      （载荷注册阻塞已于 2026-09-20 闭合）

    Dependency:
      1. `BG21_013` Whelp Smuggler 数据 `race=NONE`（类型 0，
         `is_pool_minion=False`）; **载荷本体已注册**（2026-09-20
         `batch_stats_gained`）。其效果 "Whenever a friendly Dragon gains
         Attack, give it +1 Health"（金色 +2，`num(0)`=1/2）的"获得攻击力"
         观察点已由引擎 `stats_gained` 原语落地（`Entity.add_buff` 生产点
         + 复制/复原抑制; 触发域逐路径裁定见 ENGINE_BACKLOG §E）→
         ~~缺观察点~~ **已闭合**。
         "Set its stats to 12/12" 本身有先例（`batch_spells2.SetStats` /
         `batch_trinkets14`），非阻塞项; 第二条款
         "Your Whelp Smugglers **are Dragons**"是**种族身份改写**。
      2. 引擎无任何 `GameTag.RACE` **写-读**点: 全仓脚本无 RACE 写入;
         `ApplyRaceAura` 是"对某种族加属性"（按当前 race 匹配），
         不是身份改写; `create_minion` 只在异变 `_notype_is_all`
         时改写一次。且"Your Whelp Smugglers"是**家族 + owner** 限定
         （本体 + 金色 + 绑定者棋盘），逐实体写一次无法覆盖之后获得
         的副本。
      3. 与 418 的多值种族不同: 本卡是**单值改写**（NONE → DRAGON），
         需要的是"owner 级家族种族覆写读取点"，而非 `RACES` 集合。
    Implementation path: (a) ~~迁移 `BG21_013`/`BG21_013_G` 本体~~
      **已完成 2026-09-20**（`batch_stats_gained`）;
      (b) 引擎新增 owner 级家族种族覆写（如
      `hero.race_override_families[family] = Race.DRAGON`，读取点并入
      `Minion.race` / `Entity.race`，生命周期同 `race_auras`）;
      (c) 本卡 on_bind = 交付关联卡 + 把属性设为 12/12（文本字面量，
      `num` 全 None）+ 写家族种族覆写。残余阻塞卡: BG30_MagicItem_825 +
      `BG21_013`/`_G` 的**类型改写**。
    Reference: `docs/agents/ENGINE_BACKLOG.md` §B2-4（同族）;
      `batch_trinkets12.SmugglerPortraitScript` 原台账（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（"12/12" 为文本字面量；
            BG30_MagicItem_825 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class ShakerPortraitScript:
    """
    Natural language: [x]Get a Zesty Shaker. Your Zesty Shakers give an
    extra copy of the spell.

    Status: DEFERRED — requires "额外副本数"读取点（载荷脚本改造）

    Dependency:
      1. 载荷 `BG26_505` Zesty Shaker（"Once per turn, when a
         **Spellcraft** spell is played on _this, get a new copy of it."
         ——`batch_econ_misc.ZestyShakerScript`，**已注册**）把副本数
         **写死**在 `copies = 2 if source.is_golden else 1`，且
         "每回合一次"额度私有记在 `source._shaker_turn`——
         无任何 hero 级"额外副本"读取点。
      2. 在饰品侧独立监听 `card_played` 重放该效果会**绕过**其
         "once per turn" 私有额度（要复现额度必须读另一个脚本的私有
         属性 `source._shaker_turn`——SOP §12 item 2 明令禁止），
         且会与本体脚本的副本各自结算（双份）。
      3. 本卡效果**依赖被授予卡的行为**（RULES §7.4.6 例外条款）——
         载荷虽已注册，但缺少"被本卡改造"的接口，故整卡维持
         DEFERRED（注册即 no-op = 禁止的第三态）。
    Implementation path: 引擎/载荷侧新增读取点——`hero.zesty_shaker_
      extra_copies`（owner 级，默认 0），`ZestyShakerScript` 的
      `copies = (2 if golden else 1) + hero.get(...)`（改
      `batch_econ_misc` 属主线/该批维护，本批不得改其它 batch）;
      随后本卡 on_bind = 交付关联卡（池随从 `BG26_505` → 占池）+
      `hero.zesty_shaker_extra_copies += 1`（"an extra copy" = +1，
      文本字面量）。阻塞卡: BG30_MagicItem_828。
    Reference: `batch_trinkets12.ShakerPortraitScript` 原台账
      （本批复核维持——载荷已注册，缺的是改造读取点）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（"an extra copy" 为文本字面量；
            BG30_MagicItem_828 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册本批 3 张 CORRECT 饰品（8 张 DEFERRED 不注册——SOP §6b）。

    解冻依据（作业单新原语逐个实测）:
      - 423 ← 展示位档位协议 `TAVERN_EXTRA_TIER_SLOTS`（commit 66eaa35）
      - 548 ← `spell_resolved` 后置施法时点（RULES §7.4.12）
      - 701 ← 实体级 `HEALTH_BUY` 以生命代金 + `tavern_entity_added`
              （commit 690ded8 / RULES §7.4.7/§7.4.9）
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (INNKEEPERS_STEIN, InnkeepersSteinScript),
        (GLOWSCALE_PORTRAIT, GlowscalePortraitScript),
        (EYE_OF_SARGERAS, EyeOfSargerasScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
