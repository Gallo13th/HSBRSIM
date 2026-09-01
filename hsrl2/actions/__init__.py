"""hsrl2.actions — 卡牌脚本可复用的状态变更原子（Action 子类）。

脚本层从 CardDef.num() 取数值构造这些 Action，经 run_script_hook /
run_actions 送入 ActionQueue 解析。数值一律来自调用方，本包零硬编码；
随机一律 game.rng.*；池获取一律 minion_pool.acquire（RULES §2.3/§2.4/§6.18）。
"""

from hsrl2.actions.damage import Hit
from hsrl2.actions.discover import Discover, GetRandomMinion
from hsrl2.actions.economy import GainGold, ScheduleNextTurn
from hsrl2.actions.stats import Buff, GainKeyword, LoseKeyword, Transform
from hsrl2.actions.summon import Summon, SummonPlainCopy
from hsrl2.actions.trigger import TriggerBattlecry

__all__ = [
    "Buff",
    "GainKeyword",
    "LoseKeyword",
    "Transform",
    "Summon",
    "SummonPlainCopy",
    "GainGold",
    "ScheduleNextTurn",
    "Hit",
    "GetRandomMinion",
    "Discover",
    "TriggerBattlecry",
]
