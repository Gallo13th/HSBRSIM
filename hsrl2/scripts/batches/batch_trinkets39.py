"""饰品第 39 批 —— 家族亡语改写 Portrait 解冻（2026-09-18）

本批 2 张（全部 CORRECT，商店池 Lesser 档 `spell_school=11`）:

  - `BG30_MagicItem_803` Kaboom Bot Portrait — "Get a Kaboom Bot. Your
    Kaboom Bots' <b>Deathrattles</b> deal 10 extra damage."
  - `BG32_MagicItem_820` Impulsive Portrait — "Get a 6/6 Impulsive
    Trickster. Your Impulsive Tricksters' <b>Deathrattles</b> target
    adjacent minions."

引擎读取点（沿用既有通道，零新子系统）: `hero.family_flags` +
`Game.add_family_flag` / `Game.family_flag`（RULES §7.4.16，家族"行为
开关"通道；Bristlebach Portrait `BG32_MagicItem_274` 先例 =
`batch_trinkets34`）。两条规则都是**载荷行为改写**，不是数值模板参数：

  - Kaboom: 载荷 `batch_remaining2.KaboomBotScript.deathrattle` 经
    `FLAG_KABOOM_DR_BONUS` 把逐实例 `KABOOM_EXTRA_DAMAGE`(=10) 传给
    `KaboomBlast`（`num(0) + bonus`）。
  - Impulsive: 载荷 `batch_payload_minions.ImpulsiveTricksterScript.
    deathrattle` 经 `FLAG_IMPULSIVE_ADJACENT` 把目标集合由"随机一名
    友方"改为**全部存活相邻随从**（`_adjacent_minions`）。
  两个开关常量都定义在**载荷侧**（唯一消费点），本批 import 同一常量
  （拼写漂移 fail-loud）。

权威记录（owner 权威序: wiki → 卡面天然语言）:
  两卡的 wiki 页均**无 Notes 段**（内容只有 Availability / Related
  cards / Gallery / Patch changes / External links），故按卡面天然语言
  裁定，完整推导与边界见两个载荷脚本 docstring:
  - Kaboom 金色 "twice": 一个"造成伤害的亡语实例" = 一次 "Deal num(0)
    damage"，加成**逐实例**施加 → 基础 4+10=14，金色 14+14=28。
    否决"总额 +10 一次"（= 4+4+10 = 18: 10 是奇数且两条实例各自独立
    选取目标，文本无 "split" 字样，总额读法必须凭空发明拆分规则）。
    wiki: `Battlegrounds/Kaboom_Bot_Portrait?oldid=921183`（无 Notes）;
    `Battlegrounds/Kaboom_Bot?oldid=803543`（金色 "... , twice." 与
    `num(0)=4`）。
  - Impulsive "target adjacent minions": 饰品的 "target" 替换载荷的
    目标短语 "another friendly minion"（单数）→ 复数集合; "give X to
    <集合>" 天然读法 = 每个成员各得全额 X（非均分——文本无 "split"/
    "divided"）。金色两个实例各打相邻集合 → 相邻各得 2 × max_health。
    wiki: `Battlegrounds/Impulsive_Portrait?oldid=907061`（无 Notes）;
    `Battlegrounds/Impulsive_Trickster?oldid=800847`（基础/金色文本 +
    [Random] tag）。

Impulsive 的 "Get a 6/6": 文本字面量（饰品 CardDef `num(0..4)` 全
None）——数据链关联卡 `BG21_006`（dbf 72059）经 `create_minion` 交付
后**覆盖式**设 `BASE_ATK/BASE_HEALTH/HEALTH = 6`（"Set its stats to
X/Y" 家族先例 = `batch_trinkets15.CuratorStickerScript`: `create_minion`
+ 覆盖属性 + `pending_hand_add`; `BG21_006` 运行核验
`is_pool_minion=False` → 零池操作，与 `grant_trinket_related_card`
路径等价）。Kaboom 的 "Get a Kaboom Bot" 无属性词 → 走
`batch_trinkets33._grant_related` 统一交付（数据链 + 池记账 + 满手排队）。

DEFERRED 台账迁移: `BG30_MagicItem_803` 与 `BG32_MagicItem_820` 已从
`batch_trinkets12/15/25/27/29/31/33/34` 的 DEFERRED 台账移出（本批注册;
守卫见 `hsrl2/tests/test_batch_trinkets39.py` 与各批更新后的台账）。

协议: 饰品实体经 `_offer_trinkets` 购买 / `grant_trinket` 授予 →
`hero.trinkets`；脚本只挂 `on_bind`（接线审计 W1 白名单）。

`source` 传入饰品实体: `Game.family_flag` 读取时校验其仍在
`hero.trinkets`（被替换/移除即失效——同 `giver_bonus` / `_card_aura_active`
口径）。

AMBIGUOUS 留档（记录，不据此改动）: 官方未说明同一英雄先后获得两张
同名 Portrait（`grant_trinket(..., duplicate=True)`，如 Souvenir Stand
复制）是否叠加 —— `family_flags` 为列表，重复登记不改变布尔读法的
结果（幂等）; `giver_bonus` 族则叠加。本批两张都是布尔行为开关，故
现状幂等; 该差异按"行为开关天然幂等"保留。
"""

from __future__ import annotations

from hsrl2.game import GameStateError
from hsrl2.scripts.batches.batch_payload_minions import (
    FLAG_IMPULSIVE_ADJACENT,
)
from hsrl2.scripts.batches.batch_remaining2 import FLAG_KABOOM_DR_BONUS
from hsrl2.scripts.batches.batch_trinkets33 import _grant_related
from hsrl2.tags import GameTag

KABOOM_BOT_PORTRAIT = "BG30_MagicItem_803"
IMPULSIVE_PORTRAIT = "BG32_MagicItem_820"

#: 文本字面量（`BG32_MagicItem_820` CardDef `num(0..4)` 全 None——SOP §3
#: 允许并在此声明）: "Get a **6/6** Impulsive Trickster" = 交付副本的
#: 覆盖式属性。
IMPULSIVE_STAT = 6


class KaboomBotPortraitScript:
    """
    Natural language: [x]Get a Kaboom Bot. Your Kaboom Bots'
    <b>Deathrattles</b> deal 10 extra damage.

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）:
         `game.trinket_related_card(本饰品 id)` 经 `evolution_card_id`
         数据链解析关联卡（`BG_BOT_606` Kaboom Bot）; 解析失败 →
         `GameStateError`（fail-loud，SOP §6b）
      2. `game.grant_trinket_related_card(hero, 本饰品 id)` 授予 1 份
         进手牌（池记账/满手排队由引擎负责; 池空落空非错误）
      3. `game.add_family_flag(hero, 关联卡 id, FLAG_KABOOM_DR_BONUS,
         source=source)` —— 该英雄的 Kaboom Bot（含金色，基础卡 id
         归一）的**每个亡语伤害实例** +10（消费点
         `batch_remaining2.KaboomBotScript.deathrattle` 经
         `game.family_flag` 读取，把 `KABOOM_EXTRA_DAMAGE` 传给
         `KaboomBlast`）
      4. **不改 `num(0)`**: 基础伤害仍取载荷 CardDef（基础/金色均 4）
         ——本饰品只追加"10 extra damage"（饰品 CardDef 无模板参数，
         10 为文本字面量，声明在载荷侧 `KABOOM_EXTRA_DAMAGE`）
      5. owner 隔离: 开关只写本英雄; 对手 Kaboom Bot 仍只打 4
      6. 逐实例口径的推导/否决替代读法/边界见
         `batch_remaining2.KaboomBotScript` docstring §6–8（wiki 无
         Notes → 卡面天然语言）
      7. 数值零硬编码（本条只登记规则 + 交付关联卡）

    Test: test_batch_trinkets39.py — 真实 `grant_trinket` 后手牌出现
    BG_BOT_606; 真实 `run_combat` 内亡语伤害实例 = 4+10 = 14（无饰品
    对照 4）; 金色两个实例各 14（[14, 14]）; 对手持有饰品不影响我方;
    非家族随从的伤害不受影响; 饰品被移除后开关失效

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符; "10" 为载荷侧
            文本字面量 KABOOM_EXTRA_DAMAGE）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        rel = _grant_related(game, hero, KABOOM_BOT_PORTRAIT)
        game.add_family_flag(hero, rel.id, FLAG_KABOOM_DR_BONUS,
                             source=source)
        return None


class ImpulsivePortraitScript:
    """
    Natural language: [x]Get a 6/6 Impulsive Trickster. Your Impulsive
    Tricksters' <b>Deathrattles</b> target adjacent minions.

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）:
         `game.trinket_related_card(本饰品 id)` 经 `evolution_card_id`
         数据链解析关联卡（`BG21_006` Impulsive Trickster，dbf 72059）;
         解析失败 → `GameStateError`（fail-loud，SOP §6b）
      2. 交付 **6/6** 副本（"Get a 6/6 Impulsive Trickster"——文本字面
         量 `IMPULSIVE_STAT`）: `game.create_minion(关联卡 id)` 后覆盖式
         设 `BASE_ATK/BASE_HEALTH/HEALTH = 6`（"Set its stats to X/Y"
         先例 = batch_trinkets15 CuratorSticker: `create_minion` + 覆盖
         属性 + `pending_hand_add`）。`BG21_006` `is_pool_minion=False`
         （运行核验）→ 零池操作，与 `grant_trinket_related_card` 路径
         等价; 满手经 `pending_hand_add` 排队（RULES §3.3）
      3. `game.add_family_flag(hero, 关联卡 id, FLAG_IMPULSIVE_ADJACENT,
         source=source)` —— 该英雄的 Impulsive Trickster（含金色，基础
         卡 id 归一）亡语目标集合由"随机一名友方随从"改为**全部存活
         相邻随从**（消费点
         `batch_payload_minions.ImpulsiveTricksterScript.deathrattle`
         经 `game.family_flag` 读取）
      4. **目标集合全额逐目标**（非均分）: 每个相邻随从各得全额
         `max_health`; 金色两个实例各打相邻集合 → 相邻各得
         2 × max_health。推导/否决均分读法/相邻定义与边界见
         `ImpulsiveTricksterScript` docstring §4–6（wiki 无 Notes →
         卡面天然语言）
      5. owner 隔离: 开关只写本英雄; 对手 Impulsive Trickster 仍给随机
         一名其友方
      6. 数值零硬编码（6 为文本字面量并在此声明）

    Test: test_batch_trinkets39.py — 真实 `grant_trinket` 后手牌出现
    BG21_006 且属性恰 6/6（无饰品对照 5/5）; 真实
    `_process_single_death` 下两个相邻随从各得全额 max_health（无饰品
    对照随机单目标）; 金色相邻各得 2×max_health; 对手持有饰品不影响
    我方; 非家族随从不被改写; 饰品被移除后开关失效

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符; "6/6" 为文本字面量
            IMPULSIVE_STAT）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        rel = game.trinket_related_card(IMPULSIVE_PORTRAIT)
        if rel is None:
            raise GameStateError(
                f"{IMPULSIVE_PORTRAIT}: evolution_card_id broken data chain")
        m = game.create_minion(rel.id, controller=hero)
        if m is not None:
            m.set(GameTag.BASE_ATK, IMPULSIVE_STAT)
            m.set(GameTag.BASE_HEALTH, IMPULSIVE_STAT)
            m.set(GameTag.HEALTH, IMPULSIVE_STAT)
            game.pending_hand_add(hero, m)
        game.add_family_flag(hero, rel.id, FLAG_IMPULSIVE_ADJACENT,
                             source=source)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 39 批 2 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (KABOOM_BOT_PORTRAIT, KaboomBotPortraitScript),
        (IMPULSIVE_PORTRAIT, ImpulsivePortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
