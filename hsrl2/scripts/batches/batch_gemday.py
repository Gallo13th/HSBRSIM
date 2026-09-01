"""Gem Day (BG31_893) 与零星补注册——法术清尾批次上报缺口的补充。

Gem Day: Crater Miner (BG31_320) / Gem Rat (BG31_326) 产出的
Choose One 衍生法术。"+1/+1" 为文本字面量（CardDef 无模板参数）。
"""

from hsrl2.game import PendingChoice
from hsrl2.queue import Action
from hsrl2.tags import GameTag


class _GainBloodGemBonus(Action):
    """hero 血宝石加成递增（+1/+1 文本字面量）。"""

    def __init__(self, hero, atk: int, health: int):
        self.hero = hero
        self.atk = atk
        self.health = health

    def do(self, game) -> None:
        self.hero.set(GameTag.BLOOD_GEM_BONUS_ATK,
                      self.hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0) + self.atk)
        self.hero.set(GameTag.BLOOD_GEM_BONUS_HEALTH,
                      self.hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0)
                      + self.health)


class GemDayScript:
    """
    Natural language: <b>Choose One - </b>Your <b>Blood Gems</b> give an
    extra +1 Attack this game; or +1 Health.

    Formal spec:
      1. 引擎 play_spell 的 Choose One 协议（类属性 choose_options）:
         弹出 kind="choose_one" 选择，选定 key 以 ctx["choose"] 传入
         on_play——脚本**不得**再手动创建选择框
      2. atk 分支: BLOOD_GEM_BONUS_ATK += 1; health 分支: +1 Health
      3. CHOOSE_BOTH（Thorned Trailblazer 光环/Fandral 实体 tag）:
         引擎直传 choose="both" → 双分支各执行
      4. 数值 1/1 为文本字面量（CardDef 无模板参数——36.2.2 核实）

    Test: test_gem_day.py — 两分支各自加成 / both 双效 / 施放后
          PlayBloodGems 数值受加成

    Params: 无模板参数（1/1 文本字面量）
    """

    choose_options = [("atk", "+1 Attack"), ("health", "+1 Health")]

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        key = (ctx or {}).get("choose")
        both = key == "both"
        actions = []
        if key == "atk" or both:
            actions.append(_GainBloodGemBonus(hero, 1, 0))
        if key == "health" or both:
            actions.append(_GainBloodGemBonus(hero, 0, 1))
        return actions


def register() -> list[str]:
    from hsrl2.scripts.registry import register as _register
    _register("BG31_893", GemDayScript)
    return ["BG31_893"]
