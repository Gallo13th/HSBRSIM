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
      - 触发次数 = **金色 ×2**（与 `play_minion` 打出路径同口径）+ 
        `BATTLECRY_DOUBLER` 光环（Brann 式，累加；金色 Brann ×2）
        ——2026-09-02 对抗验证 BUG-3: 旧实现只认 Brann，金色目标被重触发
        只结算 1 次（与自然打出 ×2 不一致，Hackerfin Portrait 实证）
      - 每次触发: 执行 target 的 battlecry 脚本钩子（ctx=None），返回的
        Action(s) 送入 ActionQueue 解析
      - 每次触发: 控制者 COUNTER_BATTLECRIES +1（tags.py 1046，Dark Gifts
        Battle Scars 资格计数）并广播 BATTLECRY_TRIGGER (minion=target)
        —— events.py 契约: 自然打出与重触发都广播
      - **门禁（2026-09-13, RULES §7.4.17）**: 只对 `game.has_battlecry`
        为真的随从生效——无战吼随从无效果、不计数、不广播。该门禁覆盖
        关键词 tag、脚本钩子（金卡数据缺口）与**已生效的条件化战吼**;
        官方依据: 32.4 补丁说明 Snicker Snacks 条目（"couldn't trigger
        Selfless Hero's effect when it has a Battlecry from Selfless
        Portrait"）——正因"触发战吼"以"该随从是否有战吼"为门禁，Portrait
        赋予的战吼才需要专门修复。
    """

    def __init__(self, target: "Minion") -> None:
        self.target = target

    def do(self, game: "Game") -> None:
        target = self.target
        hero = target.controller
        if not game.has_battlecry(target):
            return
        times = 2 if getattr(target, "is_golden", False) else 1
        # Brann 式光环：与 play_minion 的 extra_bc 累加口径一致
        if hero is not None:
            times += sum(2 if m.is_golden else 1 for m in hero.board
                         if m.has(GameTag.BATTLECRY_DOUBLER))
        for _ in range(times):
            result = target.call_script("battlecry", None)
            game.run_actions(result)
            if hero is not None:
                hero.set(GameTag.COUNTER_BATTLECRIES,
                         hero.get(GameTag.COUNTER_BATTLECRIES, 0) + 1)
            game.events.fire(game, BATTLECRY_TRIGGER, minion=target)
