"""发现 / 随机获取类 Action — 池约束的唯一下游消费者。

RULES §2.3: 发现/随机获取的随从从池中移除（minion_pool.acquire）。
RULES §2.4: 池中无副本的随从不可被任何玩家获取。
RULES §6.18: 池中没有的随从不会出现在发现选项中。
RULES §3.3: 满手牌生成的卡排队等待而非销毁（pending_hand_add）。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, TYPE_CHECKING

from hsrl2.game import GameStateError, PendingChoice
from hsrl2.queue import Action
from hsrl2.tags import Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


def _pool_candidates(game: "Game", race: Optional[Race] = None,
                     min_tier: Optional[int] = None,
                     max_tier: Optional[int] = None,
                     exclude: Sequence[str] = ()) -> List[str]:
    """按池剩余量 / tier / 种族过滤出的可获取 card_id 列表。

    - race 匹配: d.race == race 或 d.race == Race.ALL（Amalgam 规则——
      全种族随从匹配任何种族查询）
    - tier: min_tier <= d.tech_level <= max_tier（None = 不限）
    - 本局禁用种族（active_races）排除，NONE/ALL 永远可用
      （与 MinionPool._race_ok 一致）
    """
    pool = game.minion_pool
    excluded = set(exclude or ())
    out: List[str] = []
    for d in game.db.pool_minions():
        if d.id in excluded:
            continue
        if pool.available(d.id) <= 0:
            continue
        if min_tier is not None and d.tech_level < min_tier:
            continue
        if max_tier is not None and d.tech_level > max_tier:
            continue
        if race is not None and d.race != race and d.race != Race.ALL:
            continue
        if (pool.active_races is not None
                and d.race not in (Race.NONE, Race.ALL)
                and d.race not in pool.active_races):
            continue
        out.append(d.id)
    return out


class GetRandomMinion(Action):
    """从共享池随机获取一张随从进手牌。

    - 候选按池剩余量过滤（RULES §2.4）
    - 无候选 → do() 直接 return: 真实游戏中池空则效果落空——这是正确
      游戏行为，非静默失败
    - 选中**必须** minion_pool.acquire 占池（RULES §2.3）
    - 满手牌 → game.pending_hand_add 排队等待（RULES §3.3）
    """

    def __init__(self, hero: "Hero", race: Optional[Race] = None,
                 min_tier: Optional[int] = None,
                 max_tier: Optional[int] = None,
                 exclude: Sequence[str] = ()) -> None:
        self.hero = hero
        self.race = race
        self.min_tier = min_tier
        self.max_tier = max_tier
        self.exclude = tuple(exclude or ())

    def do(self, game: "Game") -> None:
        cands = _pool_candidates(game, self.race, self.min_tier,
                                 self.max_tier, self.exclude)
        if not cands:
            return
        card_id = game.rng.choice(cands, label="get_random_minion")
        if not game.minion_pool.acquire(card_id):
            raise GameStateError(
                f"GetRandomMinion: pool acquire failed for {card_id}")
        m = game.create_minion(card_id, controller=self.hero)
        game.pending_hand_add(self.hero, m)


class Discover(Action):
    """发现: 从候选集抽 count 个**不同** card_id 入 PendingChoice 队列。

    - 候选集 = candidates 参数显式给定，或与 GetRandomMinion 相同的池过滤
      （选项生成时已按池剩余量过滤，RULES §6.18"池中没有的随从不会出现
      在发现选项中"）
    - 候选不足 count 时全给（官方: 三选一池耗尽时给少于 3 个）
    - PendingChoice append 到 game.pending_choices（队列化——v1 单槽
      覆盖 bug 的修复，连发发现不互相覆盖）
    - resolve_callback(picked_card_id): minion_pool.acquire（选中即从池
      移除, RULES §2.3）→ create_minion → pending_hand_add；闭包内异常
      向上传播，不吞
    - 无候选 → do() 直接 return（效果落空，同 GetRandomMinion）
    """

    def __init__(self, hero: "Hero", count: int = 3,
                 race: Optional[Race] = None,
                 min_tier: Optional[int] = None,
                 max_tier: Optional[int] = None,
                 candidates: Optional[Sequence[str]] = None,
                 kind: str = "discover_minion") -> None:
        self.hero = hero
        self.count = count
        self.race = race
        self.min_tier = min_tier
        self.max_tier = max_tier
        self.candidates = candidates
        self.kind = kind

    def do(self, game: "Game") -> None:
        if self.candidates is not None:
            cands = list(dict.fromkeys(self.candidates))
        else:
            cands = _pool_candidates(game, self.race, self.min_tier,
                                     self.max_tier)
        if not cands:
            return
        k = min(self.count, len(cands))
        options = game.rng.sample(cands, k, label="discover_options")
        hero = self.hero

        def resolve(pick_id: str) -> None:
            if not game.minion_pool.acquire(pick_id):
                raise GameStateError(
                    f"Discover: pick {pick_id} no longer available in pool")
            m = game.create_minion(pick_id, controller=hero)
            game.pending_hand_add(hero, m)

        game.pending_choices.append(PendingChoice(
            hero, options, self.kind, resolve_callback=resolve))
