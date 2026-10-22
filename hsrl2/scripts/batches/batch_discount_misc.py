"""批次 discount_misc — 折扣/售价覆写族 3 张（2026-09-02，RULES §7.4.5）。

混合类别批次（wiring 审计按 CardDB 逐卡判类）:
  BG28_Reward_500    Beyond the Mirage      （任务奖励）酒馆法术持久 -1 费
  BG32_MagicItem_935 Lubber Sticker         （饰品）每次刷新多 1 张酒馆法术;
                                            每回合首张购买 -1 费
  BG27_Anomaly_721   Uncompensated Upset   （异变）开局 1 金; 随从 1 费但
                                            出售 0 金; 升级费 -2

引擎原语（本批依赖，均已在主线落地）:
  - `GameTag.TAVERN_SPELL_COST_MOD`（持久法术折扣，buy_from_tavern 消费）
  - `hero._tavern_spell_extra`（hero 级额外法术展示位，refresh_tavern 读取）
  - `GameTag.SELL_VALUE_OVERRIDE`（英雄级出售价覆写，sell_minion 读取）
  - `GameTag.TAVERN_MINION_COST_OVERRIDE` / `UPGRADE_COST_MOD`（既有）

DEFERRED: 无（本批范围内）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.events import TURN_START, Listener
from hsrl2.tags import GameTag

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


# ══════════════════ BG28_Reward_500 Beyond the Mirage ══════════════════


class BeyondTheMirageScript:
    """
    Natural language: Tavern spells cost (1) less.

    Formal spec:
      1. on_bind（奖励绑定）: `hero.set(TAVERN_SPELL_COST_MOD,
         已有 + 1)`——持久折扣（无时限; 文本无 "this turn"/"next"）
      2. 消费点 = `game.buy_from_tavern`（仅 `is_pool_spell`; 在一次性
         `NEXT_SPELL_COST_REDUCTION` 之前先减持久折扣，两者叠加）
      3. 只作用于持有者（hero 级 tag）

    Test: test_batch_discount_misc.py — 绑定后每次购买酒馆法术都少 1 金
      （连续两张对照）/ 对手不受影响 / 非法术购买不受影响

    Params: discount=1（"cost (1) less" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = (ctx or {}).get("hero")
        if hero is None:
            return None
        hero.set(GameTag.TAVERN_SPELL_COST_MOD,
                 hero.get(GameTag.TAVERN_SPELL_COST_MOD, 0) + 1)
        return None


# ══════════════════ BG32_MagicItem_935 Lubber Sticker ══════════════════


class LubberStickerScript:
    """
    Natural language: The Tavern offers an extra Tavern spell whenever it
    is <b>Refreshed</b>. The first one you buy each turn costs (1) less.

    Formal spec:
      1. on_bind: `hero._tavern_spell_extra = 1`——**hero 级**额外法术
         展示位（不得污染对手酒馆; 对照 game 级异变覆写）。
         "whenever it is Refreshed" 无主动/自动限定 → 引擎自动刷新
         （回合开始）与手动刷新都生效（引擎在 `refresh_tavern` 统一读取）
      2. 每回合首张 -1 费: on_bind（绑定当回合）+ 每回合 `start_of_turn`
         写 `NEXT_SPELL_COST_REDUCTION = 1`——引擎在**成交的**首个池法术
         购买时消费（失败购买不烧，见 buy_from_tavern）
      3. 饰品协议: 只挂 on_bind（饰品允许钩子集内）

    Test: test_batch_discount_misc.py — 绑定后（真实 refresh_tavern）法术
      展示位 +1 且对手不变 / 每回合首张法术少 1 金、第二张原价 /
      下一回合折扣重置 / 买非法术不消耗折扣

    Params: discount=1 / extra_spells=1（文本字面量；CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = (ctx or {}).get("hero")
        if hero is None:
            return None
        hero._tavern_spell_extra = getattr(hero, "_tavern_spell_extra", 0) + 1

        def _grant_discount(h):
            # **覆盖式 max**（不是 set 1）——同 tag 上可能已有其它来源
            # （Ominous Seer 等）累积的折扣，直接覆盖会静默吞掉它们
            # （2026-09-02 对抗审查 MINOR: 两次 Ominous Seer 得 3 →
            # 下回合 start_of_turn 后被抹成 1）
            h.set(GameTag.NEXT_SPELL_COST_REDUCTION,
                  max(h.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 1))

        _grant_discount(hero)

        def on_sot(g, hero=None, _h=hero, **kw):
            if hero is not _h:
                return
            _grant_discount(_h)

        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_sot))
        return None


# ══════════════════ BG27_Anomaly_721 Uncompensated Upset ══════════════════


class UncompensatedUpsetAnomaly:
    """
    Natural language: Start at 1 Gold. Minions cost (1) but sell for (0).
    Upgrading the Tavern costs (2) less.

    Formal spec:
      1. on_bind(game): 对**每个**英雄（全局异变）:
         - 第 1 回合 `TURN_START` 把金币覆写为 1（Money Match 先例;
           监听器在 `_begin_recruit_for` 基础收入重置之后触发）
         - `TAVERN_MINION_COST_OVERRIDE = 1`（随从购买价 1 金;
           既有经济钩子）
         - `SELL_VALUE_OVERRIDE = 0`（"sell for (0)"——英雄级出售价覆写，
           实体自身 SELL_VALUE tag 仍优先）
         - `UPGRADE_COST_MOD -= 2`（升级费 -2; `upgrade_tavern` 读取）
      2. 皆为 hero 级 tag → 对手同样受影响（异变是全局规则）

    Test: test_batch_discount_misc.py — 开局 1 金 / 随从实付 1 金 /
      出售 +0 金 / 升级费少 2（对照标准局）/ 全桌一致（两英雄）

    Params: gold=1 cost=1 sell=0 upgrade=-2（文本字面量）
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 1)
            h.set(GameTag.SELL_VALUE_OVERRIDE, 0)
            h.set(GameTag.UPGRADE_COST_MOD,
                  h.get(GameTag.UPGRADE_COST_MOD, 0) - 2)

            # 常驻监听 + 回合判定（`_start_gold` 先例）: **不能**用
            # `once=True` + 体内 guard——EventBus 在 condition 通过时即
            # 消费 once，而 condition 为 None 时第一个英雄的 TURN_START
            # 就会把其他英雄的监听器一并消费掉（对抗审查: 曾致仅 1 号位
            # 英雄拿到开局金币）
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is _h and turn == 1:
                    _h.gold = 1

            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))
        return None


def register() -> list[str]:
    """注册折扣/售价覆写族 3 张（混合类别）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG28_Reward_500", BeyondTheMirageScript),
        ("BG32_MagicItem_935", LubberStickerScript),
        ("BG27_Anomaly_721", UncompensatedUpsetAnomaly),
    ]
    registered = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
