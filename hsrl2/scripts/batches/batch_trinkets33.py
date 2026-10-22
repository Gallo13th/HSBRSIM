"""饰品第 33 批 —— 家族"给予者加成"Portrait（RULES §7.4.15，2026-09-13）

本批 2 张（全部 CORRECT，商店池）:

  - `BG30_MagicItem_944` Redeemer Portrait — "Get a Nalaa the Redeemer.
    Your Nalaa the Redeemers give an extra +{0}/+{1}."
  - `BG30_MagicItem_828` Shaker Portrait — "Get a Zesty Shaker. Your
    Zesty Shakers give an extra copy of the spell."

引擎读取点（本批主线新增，RULES §7.4.15）:
  `hero.giver_bonus[基础卡 id] = {atk, health, copies}` +
  `Game.add_giver_bonus` / `Game.giver_bonus`。载荷消费点:
  `batch_payload_minions.NalaaTheRedeemerScript`（+atk/+health）与
  `batch_econ_misc.ZestyShakerScript`（+copies）。金色载荷按基础卡 id
  归一命中（数值仍取各自金色 CardDef）。

关联卡授予: `game.trinket_related_card` / `grant_trinket_related_card`
（`evolution_card_id` 数据链——零硬编码卡 id）。

DEFERRED 台账（同族 Portrait，仍阻塞 → 保持未注册，SOP §6b 二态铁律）:
  - `BG30_MagicItem_868` Rewinder Portrait — 两处阻塞: (a) "Get a Soul
    Rewinder **and** a Wrath Weaver" 点名**两张**卡，而
    `evolution_card_id` 是单卡数据链（需第二条数据链或文本解析）;
    (b) "also gain Attack" 的增量**无数据字段**（文本无数值；"等于
    Health 增量"只是候选读法，无权威）。
  - `BG30_MagicItem_987` Balladist Portrait — 同上 (b): "also give
    Attack" 无增量权威（SoT "get another" 本身已可表达）。
  - `BG30_MagicItem_869` Felblood Portrait — 载荷 `BG29_873` Slimy /
    `BG29_877` Fiery Felblood **均未注册**。
  - `BG30_MagicItem_803` Kaboom Bot Portrait — ✅ **已迁出 batch_trinkets39**
    （2026-09-18）。载荷 `BG_BOT_606` / `TB_BaconUps_028` 已于 2026-09-16
    由 batch_remaining2 注册; 家族亡语伤害改写读取点 = RULES §7.4.16
    `hero.family_flags`（载荷侧 `FLAG_KABOOM_DR_BONUS`）; 金色 "twice"
    口径按 wiki `Battlegrounds/Kaboom_Bot_Portrait`（oldid=921183）
    **无 Notes 段** → 卡面天然语言 = **逐实例 +10**（14+14; 否决总额 +10
    一次 = 18，无法在两条独立伤害实例间分配）。

协议: 饰品实体经 `_offer_trinkets` 购买 / `grant_trinket` 授予 →
`hero.trinkets`；脚本只挂 `on_bind`（接线审计 W1 白名单）。

`source` 传入饰品实体: `Game.giver_bonus` 读取时校验其仍在
`hero.trinkets`（被替换/移除即失效——同 `_card_aura_active` 口径）。

AMBIGUOUS 留档（记录，不据此改动）: `grant_trinket(..., duplicate=True)`
（"transform into a copy of it" 族）会二次 `on_bind` → 加成叠加
（实测 +8/+8）并再授予 1 份关联卡。官方"持有两份同饰品"是否叠加无权威；
按"同名修正量叠加"惯例保留现状。
"""

from __future__ import annotations

from hsrl2.game import GameStateError

REDEEMER_PORTRAIT = "BG30_MagicItem_944"
SHAKER_PORTRAIT = "BG30_MagicItem_828"

NALAA = "BG28_551"
ZESTY_SHAKER = "BG26_505"


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _grant_related(game, hero, tid: str):
    """数据链授予关联卡（RULES §7.4.6）——链条断裂 fail-loud。

    解析失败 → `GameStateError`（SOP §6b，同 `batch_trinkets11
    ._related_card_id` 口径）；`grant_trinket_related_card` 返回 False
    （池空落空）不是错误，按 RULES §2.4 整卡落空。
    """
    rel = game.trinket_related_card(tid)
    if rel is None:
        raise GameStateError(f"{tid}: evolution_card_id broken data chain")
    game.grant_trinket_related_card(hero, tid)
    return rel


class RedeemerPortraitScript:
    """
    Natural language: [x]Get a Nalaa the Redeemer. Your Nalaa the
    Redeemers give an extra +{0}/+{1}.

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）:
         `game.trinket_related_card(本饰品 id)` 经 `evolution_card_id`
         数据链解析关联卡（BG28_551 Nalaa the Redeemer）; 解析失败 →
         `GameStateError`（fail-loud，SOP §6b）
      2. `game.grant_trinket_related_card(hero, 本饰品 id)` 授予 1 份
         进手牌（池记账/满手排队由引擎负责; 池空落空非错误）
      3. `game.add_giver_bonus(hero, 关联卡 id, atk=num(0), health=num(1),
         source=source)`
         —— 该英雄的 Nalaa 每次给予改成 `+num(0)+extra / +num(1)+extra`
         （消费点 `NalaaTheRedeemerScript.on_cast` 经 `game.giver_bonus`
         读取）; 金色 Nalaa 按基础卡 id 归一命中、基础量取金色 CardDef
      4. owner 隔离: 加成只写本英雄的 Nalaa; 对手同族不受影响
      5. 数值全部来自本饰品 CardDef.num（{0}/{1}），零硬编码

    Test: test_batch_trinkets33.py — 真实 `grant_trinket` 后手牌出现
    BG28_551 且基点 4/3; 施放酒馆法术给予量 = 4+4 / 3+4 = 8/7;
    对手 Nalaa 仍 4/3（owner 隔离）; 金色 Nalaa 吃加成; 无饰品对照 4/3

    Params: {0}=4 {1}=4（BG30_MagicItem_944）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        rel = _grant_related(game, hero, REDEEMER_PORTRAIT)
        game.add_giver_bonus(hero, rel.id,
                             atk=_num(game, REDEEMER_PORTRAIT, 0),
                             health=_num(game, REDEEMER_PORTRAIT, 1),
                             source=source)
        return None


class ShakerPortraitScript:
    """
    Natural language: [x]Get a Zesty Shaker. Your Zesty Shakers give an
    extra copy of the spell.

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）: 数据链解析关联卡
         （BG26_505 Zesty Shaker）→ 解析失败 `GameStateError`（fail-loud）
      2. `grant_trinket_related_card` 授予 1 份 Zesty Shaker 进手牌
      3. `game.add_giver_bonus(hero, 关联卡 id, copies=1, source=source)`
         —— 该英雄的
         Zesty Shaker 触发时额外获得 1 份法术副本（消费点
         `ZestyShakerScript.on_played`: 基础 1 / 金色 2 + copies）
      4. "an extra copy" 的 1 为文本字面量（CardDef 无模板参数）
      5. owner 隔离: 只作用于本英雄的 Zesty Shaker

    Test: test_batch_trinkets33.py — 真实 `grant_trinket` 后手牌出现
    BG26_505; Spellcraft 打在本体 → 手牌出现 **2** 份同 id 副本
    （无饰品对照 1 份）; 金色本体 + 饰品 → 3 份; 对手本体不受影响

    Params: 无模板参数（extra copies=1，卡面字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        rel = _grant_related(game, hero, SHAKER_PORTRAIT)
        game.add_giver_bonus(hero, rel.id, copies=1, source=source)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 33 批 2 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (REDEEMER_PORTRAIT, RedeemerPortraitScript),
        (SHAKER_PORTRAIT, ShakerPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
