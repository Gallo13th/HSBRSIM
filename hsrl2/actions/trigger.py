"""战吼重触发类 Action。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.events import BATTLECRY_TRIGGER
from hsrl2.queue import Action
from hsrl2.tags import GameTag

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.minion import Minion


class TriggerBattlecry(Action):
    """重触发 target 的战吼（Kelp Keeper BG36_701 Activate 等效果的底层原子）。

    官方依据（作业单 2026-08-21 裁定，触发次数模型与 play_minion 对
    Brann 的处理一致）:
      - 触发次数 = 2 若 target 控制者棋盘存在 BATTLECRY_DOUBLER 光环
        （Brann 式，官方对重触发同样翻倍），否则 1
      - 每次触发: 执行 target 的 battlecry 脚本钩子（ctx=None），返回的
        Action(s) 送入 ActionQueue 解析（金色×2 由 play_minion 的打出路径
        处理，重触发路径是否对金色目标翻倍官方未说明，按作业单公式不翻倍，
        见批次报告 SPEC_GAP）
      - 每次触发: 控制者 COUNTER_BATTLECRIES +1（tags.py 1046，Dark Gifts
        Battle Scars 资格计数）并广播 BATTLECRY_TRIGGER (minion=target)
        —— events.py 契约: 自然打出与重触发都广播
    """

    def __init__(self, target: "Minion") -> None:
        self.target = target

    def do(self, game: "Game") -> None:
        target = self.target
        hero = target.controller
        times = 2 if game._battlecry_doubled(hero) else 1
        for _ in range(times):
            result = target.call_script("battlecry", None)
            game.run_actions(result)
            if hero is not None:
                hero.set(GameTag.COUNTER_BATTLECRIES,
                         hero.get(GameTag.COUNTER_BATTLECRIES, 0) + 1)
            game.events.fire(game, BATTLECRY_TRIGGER, minion=target)
