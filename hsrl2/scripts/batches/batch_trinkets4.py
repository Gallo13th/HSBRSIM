"""批次 trinkets4 — 饰品第四批（作业单 2026-09-02，主线实现）。

与 batch_trinkets3 的作业单 id 集合互不相交（避免重复注册）。

实现 4 张（data/bg_trinkets.json 文本 + num 参数为准）:
  - BG30_MagicItem_914 Nerglish Phrasebook — 打出一个随从后，手牌最左
    随从 +3/+3
  - BG30_MagicItem_988 Great Boar Sticker — 获得 3 颗血宝石；你的血宝石
    额外 +num(0)/+num(1)（BLOOD_GEM_BONUS_ATK/HEALTH）
  - BG30_MagicItem_864 Gilnean Thorned Rose — Avenge(num(0)): 你的随从
    +num(1)/+num(2) 永久，然后各受 1 点伤害
  - BG30_MagicItem_923 Elementium Chest — 每场战斗中每 2 个友方海盗攻击后，
    下回合获得 1 金

协议: 饰品实体经 `_offer_trinkets` 购买 → `hero.trinkets`；脚本挂
`on_bind(source, game, ctx)`（ctx={"hero": hero}）+ 事件监听；Avenge 走
引擎 `avenge_threshold` 类属性（仅战斗内计数，每场重置）。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainGold, Hit
from hsrl2.actions.bloodgem import GetBloodGems
from hsrl2.events import (
    AFTER_ATTACK, CARD_PLAYED, COMBAT_END, Listener,
)
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race


def _hero(ctx):
    return ctx.get("hero") if ctx else None


class T914:
    """After you play a minion, give the left-most minion in your hand
    +3/+3.

    Formal spec:
      1. on_bind: 持久监听 card_played(card=)——card 为 Minion 且
         controller is 本人（法术不触发）
      2. 目标 = 手牌中**最左的随从**（跳过法术/非随从手牌）
      3. 授予 Buff(+num(0)/+num(1))；无手牌随从 → 落空

    Test: test_batch_trinkets4.py — 打出随从后手牌最左**随从** +3/+3
    （法术在更左也不受影响）/ 对手打出不触发 / 法术打出不触发

    Params: atk=3 health=3（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)

        def on_played(g, card=None, **kw):
            if card is None or card.controller is not h:
                return
            if not isinstance(card, Minion):
                return
            hand_minions = [e for e in h.hand if isinstance(e, Minion)]
            if not hand_minions:
                return
            g.run_actions(Buff(hand_minions[0], atk=3, health=3))

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                       callback=on_played))


class T988:
    """Get 3 Blood Gems. Your Blood Gems give an extra +{0}/+{1}.

    Formal spec:
      1. on_bind: GetBloodGems(本人, 3)（进手牌; 满手排队 RULES §3.3）
      2. hero.BLOOD_GEM_BONUS_ATK += num(0)、
         hero.BLOOD_GEM_BONUS_HEALTH += num(1)——读取侧
         hsrl2/actions/bloodgem.py（血宝石数值 = 基础 + 该对 tag）

    Test: test_batch_trinkets4.py — 入手 3 张血宝石 / 打出的血宝石数值
    比基础多 num(0)/num(1) / 对手增益不受影响

    Params: {0}=2 {1}=1（script_data_num_1/2）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        d = game.db.get(source.card_id)
        game.run_actions(GetBloodGems(h, 3))
        h.set(GameTag.BLOOD_GEM_BONUS_ATK,
              h.get(GameTag.BLOOD_GEM_BONUS_ATK, 0) + (d.num(0) or 0))
        h.set(GameTag.BLOOD_GEM_BONUS_HEALTH,
              h.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0) + (d.num(1) or 0))


class T864:
    """Avenge ({0}): Give your minions +{1}/+{2} permanently and deal 1
    damage to them.

    Formal spec:
      1. avenge_threshold = num(0)=3（与数据一致，测试断言）
      2. avenge: 对本人棋盘**每个存活**随从依次 Buff(num(1), num(2))
         后造成 1 点伤害（先增益后伤害——文本顺序）；伤害走 Hit
         （圣盾/剧毒交互一致），可能造成死亡并再次计入 Avenge（官方同）
      3. 仅战斗内计数（引擎 Avenge 阶段守卫，RULES §6.11）

    Test: test_batch_trinkets4.py — 3 次友方战斗内死亡后全部随从
    +num(1)/+num(2) 且各受 1 伤 / 招募期死亡不触发 / num 与数据一致

    Params: {0}=3 {1}=4 {2}=5（script_data_num_1/2/3）
    """

    # 阈值须为类属性（引擎读取）; 与 CardDef.num(0) 一致性由测试守护
    avenge_threshold = 3

    @staticmethod
    def avenge(source, game, ctx):
        d = game.db.get(source.card_id)
        atk, health = d.num(1) or 0, d.num(2) or 0
        for m in list(source.controller.board):
            if m.dead:
                continue
            game.run_actions(Buff(m, atk=atk, health=health))
            game.run_actions(Hit(m, 1))


class T923:
    """Each combat, after 2 friendly Pirates attack, gain 1 Gold next
    turn. ({0} left!)

    Formal spec:
      1. on_bind: 持久监听 after_attack(attacker=, defender=)——
         仅战斗内、attacker 为本人且 race ∈ (PIRATE, ALL)
      2. 计数每满 num(0)=2 → 清零并 defer GainGold(1)（下回合基础收入
         之上叠加，_begin_recruit_for 顺序保证）
      3. 每场战斗计数清零（combat_end）——"Each combat" 语义

    Test: test_batch_trinkets4.py — 2 个友方海盗攻击后下回合 +1 金 /
    非海盗攻击不计数 / 招募期不计数 / combat_end 清零

    Params: {0}=2（script_data_num_1）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        d = game.db.get(source.card_id)
        threshold = d.num(0) or 0
        state = {"n": 0}

        def on_attack(g, attacker=None, defender=None, **kw):
            if not g.in_combat or attacker is None:
                return
            if attacker.controller is not h:
                return
            if attacker.race not in (Race.PIRATE, Race.ALL):
                return
            state["n"] += 1
            if threshold and state["n"] >= threshold:
                state["n"] = 0
                g.defer_until_next_turn(h, GainGold(h, 1))

        def on_combat_end(g, **kw):
            state["n"] = 0

        game.events.register(Listener(event=AFTER_ATTACK, owner=source,
                                       callback=on_attack))
        game.events.register(Listener(event=COMBAT_END, owner=source,
                                       callback=on_combat_end))


def register() -> list[str]:
    """注册饰品第四批 4 张。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_914", T914),
        ("BG30_MagicItem_988", T988),
        ("BG30_MagicItem_864", T864),
        ("BG30_MagicItem_923", T923),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
