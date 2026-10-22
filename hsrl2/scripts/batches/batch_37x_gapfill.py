"""缺失脚本收口：BG32_234 Dastardly Drust + BG34_922 Maelstrom Emergent。

Drust 使用 F-12 `minion_gained` 统一入手事件（单点，不重复计数）；
Maelstrom 使用 F-12 `combat_spell_extra_casts` 通道（战斗内生效）。
两张均非池卡（历史轨迹卡），数据以 CardDefs 37.0 为准。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import Buff
from hsrl2.events import DEATH, Listener
from hsrl2.tags import Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.minion import Minion

_DRUST_ID = "BG32_234"
_DRUST_G = "BG32_234_G"
_MAELSTROM_ID = "BG34_922"
_MAELSTROM_G = "BG34_922_G"
_MAELSTROM_IDS = frozenset({_MAELSTROM_ID, _MAELSTROM_G})
_PIRATE_RACES = (Race.PIRATE, Race.ALL)


class DastardlyDrustScript:
    """
    Natural language: [x]Whenever you get a Pirate, give your minions
    +{0}/+{1}. Give Golden ones +{2}/+{3} instead.

    Formal spec:
      1. on_summon 注册持久 `minion_gained` 监听（owner=source；
         F-12 单点入手事件，购买/Discover/生成/满手排队后入手全路径）。
      2. 条件: 获得的实体是 Minion、controller is source.controller；
         race ∈ {PIRATE, ALL}（"you get a Pirate"；Amalgam 全类型计入）。
      3. 触发: 对本人**棋盘**全部存活随从（含 Drust 自身）施加
         Buff(+num(0)/+num(1))；若获得的 Pirate 是**金色** → 改用
         +num(2)/+num(3)（"Give Golden ones ... instead" = 金色 Pirate
         触发金色数值；金色 Drust 的 CardDef 数值自然翻倍）。
      4. 满手排队期间不触发（真正入手时才广播）；对手获得不触发；
         非 Pirate 不触发。

    Test: test_batch_37x_gapfill.py — 普通/金色 Pirate、金色 Drust、
    真实 buy / pending_hand_add / Discover 类入手、非 Pirate/对手负例。

    Params: {0}=2 {1}=2 {2}=6 {3}=6（BG32_234；金色 4/4/12/12）
    """

    @staticmethod
    def on_summon(source: "Minion", game: "Game", ctx=None):
        hero = source.controller
        if hero is None:
            return None

        def on_minion_gained(g, hero=None, minion=None, **kw):
            if minion is None or hero is not source.controller:
                return
            if minion.controller is not source.controller:
                return
            if minion.race not in _PIRATE_RACES:
                return
            d = g.db.get(source.card_id)
            if d is None:
                return
            golden = bool(minion.is_golden)
            atk = d.num(2) if golden else d.num(0)
            health = d.num(3) if golden else d.num(1)
            if atk is None or health is None:
                return
            actions = [Buff(m, atk=atk, health=health, source=source)
                       for m in list(hero.board) if not m.dead]
            if actions:
                g.run_actions(actions)

        game.events.register(Listener(event="minion_gained", owner=source,
                                      callback=on_minion_gained))
        return None


class MaelstromEmergentScript:
    """
    Natural language: Your spells cast an extra time in combat.
    （金色: Your spells cast 2 extra times in combat.）

    Formal spec:
      1. on_summon 注册 `death` 监听（owner=source）：本体死亡时按
         剩余存活 Maelstrom 重算 hero 通道（多个叠加）；`on_sell`
         出售时重算（排除本体）。
      2. start_of_combat: 重算 `hero._combat_spell_extra_casts` =
         Σ 存活 Maelstrom 的额外次数（普通 num(0)=1，金色文本
         "2 extra times" 字面量 = 2——金色 CardDef num(0)=1 未随文本
         更新，以金色文本为准，见 docstring Params）。
      3. 只有 `cast_spell_effect` 且 `game.in_combat` 消费该值
         （F-12 原语）；招募期不生效。
      4. 本体离场/死亡后由监听/出售钩子清零或重算，不留跨战斗脏值。

    Test: test_batch_37x_gapfill.py — 战斗内 1 张 → 法术结算 2 次 /
    金色 → 3 次 / 招募期 1 次 / 无 Maelstrom 1 次 / 死亡或出售后清 0。

    Params: {0}=1（BG34_922；金色文本 "2 extra times" 字面量 2）
    """

    @staticmethod
    def _recompute(game: "Game", hero, exclude=None) -> None:
        total = 0
        for m in list(hero.board):
            if m is exclude or m.dead or m.card_id not in _MAELSTROM_IDS:
                continue
            if m.is_golden:
                total += 2          # 金色文本 "2 extra times" 字面量
            else:
                d = game.db.get(m.card_id)
                value = d.num(0) if d is not None else None
                total += int(value) if value is not None else 1
        hero._combat_spell_extra_casts = total

    @staticmethod
    def on_summon(source: "Minion", game: "Game", ctx=None):
        hero = source.controller
        if hero is None:
            return None

        def on_death(g, minion=None, **kw):
            if minion is source:
                MaelstromEmergentScript._recompute(g, hero)

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        return None

    @staticmethod
    def start_of_combat(source: "Minion", game: "Game", ctx=None):
        hero = source.controller
        if hero is not None and not source.dead:
            MaelstromEmergentScript._recompute(game, hero)
        return None

    @staticmethod
    def on_sell(source: "Minion", game: "Game", ctx=None):
        hero = source.controller
        if hero is not None:
            MaelstromEmergentScript._recompute(game, hero, exclude=source)
        return None


def register() -> list[str]:
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (_DRUST_ID, DastardlyDrustScript),
        (_DRUST_G, DastardlyDrustScript),
        (_MAELSTROM_ID, MaelstromEmergentScript),
        (_MAELSTROM_G, MaelstromEmergentScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
