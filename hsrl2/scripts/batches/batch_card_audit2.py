"""卡牌审计第二轮：Bristleback Bully（BG35_432/_G）补齐亡语。

来源：官方 CardDefs 37.0.0.255130（`data/bg_cards.json` 同源）：
  * BG35_432  Bristleback Bully（T2 3/2，Taunt，Deathrattle）
    "Get a Blood Gem that also gives a Quilboar Taunt."
  * BG35_432_G（6/4）"Get 2 Blood Gem**s** that also give ..."
token：`BG20_GEM_Taunt`（Blood Gem；"If it's a Quilboar, also give it
Taunt"）已注册为 `BloodGemTauntScript`。

本批之前 BG35_432/_G **无脚本**（REGISTRY 无登记），差分 TOP 卡
mean TVD .496；本文件只补“亡语入手 token”这一官方文本直接给出的行为，
不改引擎/其它卡。
"""

from __future__ import annotations

from hsrl2.scripts.registry import register as _register

GEM_TAUNT = "BG20_GEM_Taunt"      # 官方 Blood Gem "also gives Quilboar Taunt"


class BristlebackBullyScript:
    """
    Natural language: <b>Taunt</b> <b>Deathrattle:</b> Get a
    <b>Blood Gem</b> that also gives a Quilboar <b>Taunt</b>.
    （金色：Get 2 Blood Gems ...）

    Formal spec:
      1. deathrattle: controller 获得 `BG20_GEM_Taunt` 的**手牌副本**
         （1 份；金色 2 份）。
      2. "Get a <spell>" 族统一入口 `game.grant_card_copy_to_hand`
         （池记账/满手 pending 队列；token 不存在时 fail-safe 落空）。
      3. Taunt 是本体静态关键词（CardDB/CardDef 已给），本脚本不处理。
      4. 该宝石的“若目标是野猪人则也给 Taunt”由
         `BloodGemTauntScript`（既有实现）负责；本卡只负责 Get。

    Test: test_batch_card_audit2.py — 真实 destroy_minion 亡语入手 1 张 /
    金色 2 张 / token 正确；无脚本时不会触发（旧状态）。
    """

    copies = 1

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        card_def = game.db.get(GEM_TAUNT)
        if card_def is None:
            return None
        copies = (BristlebackBullyGoldenScript.copies
                  if source.is_golden else BristlebackBullyScript.copies)
        for _ in range(copies):
            if not game.grant_card_copy_to_hand(hero, card_def):
                break
        return None


class BristlebackBullyGoldenScript(BristlebackBullyScript):
    """金色：亡语获取 2 张 `BG20_GEM_Taunt`。"""

    copies = 2


def register() -> list[str]:
    _register("BG35_432", BristlebackBullyScript)
    _register("BG35_432_G", BristlebackBullyGoldenScript)
    return ["BG35_432", "BG35_432_G"]
