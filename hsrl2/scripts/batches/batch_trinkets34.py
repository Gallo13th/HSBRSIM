"""饰品第 34 批 —— 家族"行为开关"改写（RULES §7.4.16，2026-09-13）

本批 1 张（全部 CORRECT，商店池 Greater 档 spell_school=12）:

  - `BG32_MagicItem_274` Bristlebach Portrait — "Get a Bristlebach.
    Your Bristlebachs play **Blood Gems on all friendly minions**."

引擎读取点（本批主线新增，RULES §7.4.16）:
  `hero.family_flags: [(source, 基础卡 id, 开关名)]` +
  `Game.add_family_flag` / `Game.family_flag`——Portrait 对载荷**行为
  分支**（目标集合）的改写；数值面仍全在载荷 CardDef（§7.4.15
  `giver_bonus` 管数值，本通道管"打谁/是否多做一件事"）。
  载荷消费点: `batch_payload_minions.BristlebachScript.avenge` 读
  `FLAG_SCOPE_ALL_FRIENDLY`（常量定义在载荷侧 = 唯一消费点）。
  金色载荷 `BG26_157_G` 按基础卡 id 归一同族命中（颗数仍取各自 CardDef:
  基础 2 / 金色 4）。

关联卡授予: `game.trinket_related_card` / `grant_trinket_related_card`
（`evolution_card_id=100997` → `BG26_157` 数据链——零硬编码卡 id）。

前序台账（`batch_trinkets14` / `batch_trinkets24` §G，2026-09-13 复核）:
  该卡曾 DEFERRED，两条阻塞**均已消除**:
    (a) 载荷 `BG26_157` Bristlebach **未注册** → 已由
        `batch_payload_minions` 注册（Avenge(2) + `PlayBloodGems`，含
        金色 `BG26_157_G`）——原台账此条已陈旧;
    (b) "目标范围改为全体友方"缺引擎读取点 → 本批 §7.4.16 落地。
  文本无模板参数（Params: 无 `{0}/{1}`）: 组数/颗数全部在载荷。

协议: 饰品实体经 `_offer_trinkets` 购买 / `grant_trinket` 授予 →
`hero.trinkets`；脚本只挂 `on_bind`（接线审计 W1 白名单）。

`source` 传入饰品实体: `Game.family_flag` 读取时校验其仍在
`hero.trinkets`（被替换/移除即失效——同 `_card_aura_active` 口径）。

AMBIGUOUS 留档（记录，不据此改动）: 官方未说明被授予的 Bristlebach
本体是否也获得"全体友方"改写之外的其它变化（如金色化）——`evolution_card_id`
单卡数据链授予**基础**版本（`Get a Bristlebach` 无 "golden" 字样），
与 `BG30_MagicItem_944` / `_828` 同口径。
"""

from __future__ import annotations

from hsrl2.scripts.batches.batch_payload_minions import (
    FLAG_SCOPE_ALL_FRIENDLY,
)
from hsrl2.scripts.batches.batch_trinkets33 import _grant_related

BRISTLEBACH_PORTRAIT = "BG32_MagicItem_274"


class BristlebachPortraitScript:
    """
    Natural language: [x]Get a Bristlebach. Your Bristlebachs play
    <b>Blood Gems</b> on all friendly minions.

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）:
         `game.trinket_related_card(本饰品 id)` 经 `evolution_card_id`
         数据链解析关联卡（BG26_157 Bristlebach）; 解析失败 →
         `GameStateError`（fail-loud，SOP §6b）
      2. `game.grant_trinket_related_card(hero, 本饰品 id)` 授予 1 份
         进手牌（池记账/满手排队由引擎负责; 池空落空非错误）
      3. `game.add_family_flag(hero, 关联卡 id, FLAG_SCOPE_ALL_FRIENDLY,
         source=source)` —— 该英雄的 Bristlebach（含金色，基础卡 id
         归一）Avenge 目标集合由"你的野猪人"放宽为"全体存活友方随从"
         （消费点 `BristlebachScript.avenge` 经 `game.family_flag` 读取）
      4. **不改颗数**: 血宝石颗数仍取载荷 CardDef 文本（基础 2 / 金色 4）
         ——本饰品只改目标集合，不得在本脚本内复刻载荷的血宝石逻辑
         （SOP §12）
      5. owner 隔离: 开关只写本英雄; 对手 Bristlebach 仍只打其野猪人
      6. "all friendly minions" 含本体自身与所有类型（非野猪人亦命中）;
         `My` 限定为控制者棋盘，对手随从永不在域内
      7. 数值零硬编码（本饰品 CardDef 无模板参数）

    Test: test_batch_trinkets34.py — 真实 `grant_trinket` 后手牌出现
    BG26_157; 战斗内 Avenge 达标 → **非野猪人**友方随从同样 +2 颗
    （无饰品对照组 0）; 对手随从不受影响; 金色本体 4 颗且吃开关;
    饰品被移除后开关失效; 对手持有饰品不影响我方

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        rel = _grant_related(game, hero, BRISTLEBACH_PORTRAIT)
        game.add_family_flag(hero, rel.id, FLAG_SCOPE_ALL_FRIENDLY,
                             source=source)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 34 批 1 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (BRISTLEBACH_PORTRAIT, BristlebachPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
