"""卡牌审计第二轮：Moonsteel Juggernaut（BG31_171/_G）EoT 卫星。

官方 CardDefs 37.0.0.255130：
  * BG31_171  Moonsteel Juggernaut（T6 8/8）
    "At the end of your turn, get two {1}/{1} Magnetic Satellites and
     improve this."
  * BG31_171_G（16/16，{1}=12）
token：BG31_171t Satellite 6/6；BG31_171_Gt 12/12（Magnetic）。

真实证据（bridge-analyst `evidence_round2.json`，HDT trace；Power.log 无
原始 EoT 序列）：
  * 普通：SCN1=当前 Satellite 数值，SCN2=SCN1+6；258fe... 72→78、
    652075... 18→24；手牌 6/12/18 与历史档位一致。
  * 金色：0311764c... 102→114（+12）。
  * 结论：EoT 发两张**当前档**卫星，然后未来档 +6/+12；不是给本体加属性。
本文件只实现该直接证据；SCN 槽位由 CardDef/脚本内部计数，不读 HDT 槽位。
"""

from __future__ import annotations

from hsrl2.events import TURN_END, Listener
from hsrl2.scripts.registry import register as _register
from hsrl2.tags import GameTag

SATELLITE = "BG31_171t"
SATELLITE_G = "BG31_171_Gt"


class MoonsteelJuggernautScript:
    """
    Natural language: At the end of your turn, get two {1}/{1}
    Magnetic Satellites and improve this.

    Formal spec:
      1. on_summon: 初始化实体级 `_moonsteel_next = CardDef.num(1)`
         （普通 6 / 金色 12）；注册 `TURN_END` 持久监听器（owner=source）。
      2. EoT: 若本体仍存活/在 PLAY，创建两张当前档 Satellite 进手牌
         （`create_minion` + 数值覆盖 + `pending_hand_add`；满手排队）。
      3. 发完后 `_moonsteel_next += CardDef.num(1)`（普通 +6 / 金色 +12）。
         证据：SCN2 = SCN1 + 6/12；手牌旧档保留。
      4. 不修改本体 atk/health（证据未能观察本体变化；文本 "improve this"
         在 trace 中体现为未来 Satellite 档位）。
      5. 令牌/金色由 CardDef 的 token id 与 `num(1)` 自然体现；无新原语。

    Test: test_batch_card_audit3.py — 首次 EoT 两张 6/6、第二次两张
    12/12；金色首次 12/12、第二次 24/24；本体属性不变；满手排队不丢。
    """

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        if d is None or d.num(1) is None:
            return None
        source._moonsteel_next = int(d.num(1))

        def on_turn_end(g, turn=None, **kw):
            if source.dead:
                return
            current = int(getattr(source, "_moonsteel_next",
                                  int(d.num(1))))
            token_id = SATELLITE_G if source.is_golden else SATELLITE
            for _ in range(2):
                token = g.create_minion(token_id, controller=hero)
                if token is None:
                    continue
                token.set(GameTag.BASE_ATK, current)
                token.set(GameTag.ATK, current)
                token.set(GameTag.BASE_HEALTH, current)
                token.set(GameTag.HEALTH, current)
                g.pending_hand_add(hero, token)
            source._moonsteel_next = current + int(d.num(1))

        game.events.register(Listener(event=TURN_END, owner=source,
                                      callback=on_turn_end))
        return None


def register() -> list[str]:
    _register("BG31_171", MoonsteelJuggernautScript)
    _register("BG31_171_G", MoonsteelJuggernautScript)
    return ["BG31_171", "BG31_171_G"]
