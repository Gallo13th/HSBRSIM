"""批次 37x_firelands — F-06 原语解锁：BG35_882 Firelands Fugitive +
载荷 BG35_910 Conflagration。

背景
═══════════════════════════════════════════════════════════════════════
`batch_37x_payloadgap1` 台账 D 类：Conflagration
"Give a minion +{0}/+{1}. (Improved by each Elemental you played this
turn!)" 需要**本回合**元素打出计数；引擎此前只有游戏长
`COUNTER_ELEMENTALS_PLAYED`。本批先落 F-06 引擎原语
（`Hero.elementals_played_this_turn` + `_begin_recruit_for` 清零 +
`Game.elementals_played_this_turn(hero)` 公开读取点，见
`docs/ENGINE_NOTES.md` F-06 / `hsrl2/tests/test_turn_elemental_counter.py`），
再注册载荷 + 宿主。

卡牌
═══════════════════════════════════════════════════════════════════════
  BG35_910 Conflagration（非池 T4 酒馆法术，cost 2）
      Give a minion +{0}/+{1}. (Improved by each Elemental you played
      this turn!)
  BG35_882 / _G Firelands Fugitive（池内 T4 元素）
      <b>Battlecry and Deathrattle:</b> Get a Conflagration.
      （金色 "Get 2 Conflagrations"——BC 引擎金色双触发、DR 单次分支）

数值/语义权威
═══════════════════════════════════════════════════════════════════════
- 数值一律 `CardDef.num(i)`（37.0.0.255130；BG35_910 NUM_1=NUM_2=4）。
- "Improved by each Elemental you played this turn" = Improve 家族口径:
  每次 **+印面值**（4/4），总倍率 `1 + 本回合元素打出数`（首段 + 每个
  元素再重复一次）；计数源 = F-06 `Game.elementals_played_this_turn`
  （普通打出路径；不含召唤/磁力吸附，见 F-06 边界）。
- 增益经 `actions.racefx.tavern_spell_buff`——自动叠加
  `TAVERN_SPELL_EXTRA_ATK/HEALTH`（Shoalfin Mystic / Dark Puppeteer /
  既有酒馆法术家族统一出口）。
- 池记账: Conflagration 非池（`is_pool_spell=False`）→ 宿主 Get 走
  `create_spell` 直造、零 spell_pool；满手 `pending_hand_add` 排队。

Test: `hsrl2/tests/test_batch_37x_firelands.py`（真实 `play_spell` 定向
PendingChoice / 真实 `play_minion` 元素计数 / 真实 `destroy_minion` /
真实 `end_recruit_phase` 回合清零；正负对照 + 金色独立 CardDef）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.game import GameStateError
from hsrl2.minion import Minion

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

CONFLAGRATION = "BG35_910"
FIRELANDS_FUGITIVE = "BG35_882"
FIRELANDS_FUGITIVE_G = "BG35_882_G"


def _num(game: "Game", card_id: str, index: int) -> int:
    """`CardDef.num(index)` 权威取值; 缺失 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return int(value)


def _spell_target(ctx):
    target = (ctx or {}).get("target")
    return target if isinstance(target, Minion) else None


class ConflagrationScript:
    """
    Natural language: Give a minion +{0}/+{1}. <i>(Improved by each
    Elemental you played this turn!)</i>

    依据: CardDefs 37.0 BG35_910（非池 T4 酒馆法术，cost 2，
    NUM_1=NUM_2=4；无金色独立 CardDef——非池法术单定义）。

    Formal spec:
      1. needs_target=True（"Give a minion"）: `target_candidates` =
         己方棋盘全部存活随从; 无候选时引擎落空但法术消耗。
      2. Improve 倍率 = 1 + `Game.elementals_played_this_turn(hero)`
         （F-06；含当前已打出的元素，不含召唤/磁力吸附）。
      3. 目标获得 NUM_1×倍率 / NUM_2×倍率（"Improved by each" = 印面值
         逐次叠加，Improve 家族口径）；经 `tavern_spell_buff` 叠加
         TAVERN_SPELL_EXTRA_*。
      4. 无目标 → 落空（法术仍消耗）。

    Test: test_batch_37x_firelands.py — 0 元素 +4/+4 / 2 元素 +12/+12 /
    回合结束后计数清零 → +4/+4 / 只统计"打出"不统计召唤 / EXTRA 叠加 /
    定向 PendingChoice 协议。

    Params: {0}=4 {1}=4（Improve 增量 = 印面值）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board if not m.dead]

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        hero = source.controller
        d = game.db.get(source.card_id)
        mult = 1 + game.elementals_played_this_turn(hero)
        return [tavern_spell_buff(target,
                                  int(d.num(0)) * mult,
                                  int(d.num(1)) * mult)]


class FirelandsFugitiveScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get a
    Conflagration.

    依据: CardDefs 37.0 BG35_882（池内 T4 4/5 Elemental，
    BATTLECRY/DEATHRATTLE）；金色 BG35_882_G 文本
    "Get 2 Conflagrations"。

    Formal spec:
      1. battlecry: Get 1 张 Conflagration（非池法术 → `create_spell`
         直造，零 spell_pool；满手 `pending_hand_add` 队列）。
      2. deathrattle: 1 张（基础）/ 2 张（金色——亡语不被引擎翻倍，
         脚本按金色文本分支）。
      3. 金色 battlecry 由引擎金色战吼双触发实现总额 2。

    Test: test_batch_37x_firelands.py — BC 1 / 金色 BC 2（引擎双触发）/
    真实 destroy DR 1 / 金色 DR 2 / 非池法术不动 spell_pool / 满手排队。

    Params: 无数值参数（份数 = 文本字面量 1/2）
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        game.grant_card_copy_to_hand(hero, game.db.get(CONFLAGRATION))
        return None

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        for _ in range(count):
            game.grant_card_copy_to_hand(hero, game.db.get(CONFLAGRATION))
        return None


def register() -> list[str]:
    """注册 3 id（Conflagration + Firelands 基础/金色）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (CONFLAGRATION, ConflagrationScript),
        (FIRELANDS_FUGITIVE, FirelandsFugitiveScript),
        (FIRELANDS_FUGITIVE_G, FirelandsFugitiveScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
