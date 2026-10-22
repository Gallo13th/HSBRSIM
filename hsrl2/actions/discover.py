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
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


def _pool_candidates(game: "Game", race: Optional[Race] = None,
                     min_tier: Optional[int] = None,
                     max_tier: Optional[int] = None,
                     exclude: Sequence[str] = (),
                     hero: Optional["Hero"] = None) -> List[str]:
    """按池剩余量 / tier / 种族过滤出的可获取 card_id 列表。

    - race 匹配: **类型身份集合**——`race in identity`（`CardDef.races` =
      CARDRACE ∪ per-race tag; `Race.ALL` 展开为全 10 族，Amalgam 规则;
      双类型随从对任一所属类型均命中——wiki `Multi-type minion`
      revid 855346）。`hero` 给出时身份取 `Game.effective_races(hero, d)`
      （含家族类型改写: 825 的 Dev Comment "you see in the Tavern or
      Discover as well"——wiki Patch 30.2.0.205267 revid 814123）。
    - tier: min_tier <= d.tech_level <= max_tier; **未显式给 max_tier 时
      上限 = `game.max_tavern_tier`**（标准局 6）——2026-09-02 对抗审查
      修复: 旧实现"None = 不限"让 `GetRandomMinion` / "Get a random
      <race> minion" 族能抽到 Tier 7 随从（实测 8.7% 采样为 T7），
      越出本局可得范围。显式 `min_tier=7`（"Discover a Tier 7 minion"
      族）仍可越档。
    - 本局禁用种族（active_races）排除，NONE/ALL 永远可用
      （与 MinionPool._race_ok 一致）
    - **存在档白名单**（异变 101/102 `game._tavern_tier_ladder`）:
      非存在档的随从在当局不存在，既不进酒馆也不可作为发现/随机获取
      候选（"Only Tavern Tiers 1, 3, and 5 exist."）。
    """
    pool = game.minion_pool
    excluded = set(exclude or ())
    ladder = getattr(game, "_tavern_tier_ladder", None)
    if max_tier is None:
        max_tier = max(getattr(game, "max_tavern_tier", 6), min_tier or 0)
    out: List[str] = []
    for d in game.db.pool_minions():
        if d.id in excluded:
            continue
        if pool.available(d.id) <= 0:
            continue
        if ladder is not None and d.tech_level not in ladder:
            continue
        if min_tier is not None and d.tech_level < min_tier:
            continue
        if max_tier is not None and d.tech_level > max_tier:
            continue
        identity = (game.effective_races(hero, d) if hero is not None
                    else d.races)
        if race is not None:
            want = Race(race)
            if want == Race.ALL:
                # 旧哨兵语义保留: 查询 "All 型" 只命中 ALL 本体（"get a
                # random minion of this type" 的 source 恰为 ALL 时）。
                # 反向（查询具体族命中 ALL）由 `want in identity` 承担。
                if d.race != Race.ALL:
                    continue
            elif want not in identity:
                continue
        if (pool.active_races is not None
                and d.race not in (Race.NONE, Race.ALL)
                and not (identity & set(pool.active_races))):
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
                                 self.max_tier, self.exclude,
                                 hero=self.hero)
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
    - **预留语义**（2026-09-01 压测修复）: 选项生成时即 `acquire` 预留，
      resolve 时保留选中项、释放其余选项。依据: 官方选项中一旦展示即
      "锁定"（同时行动的其他玩家取走池中副本不影响已展示的选项），
      且旧实现"生成时不占池、resolve 才 acquire"在多发现并发时会让
      后一个发现的选项被前一个取走 → `GameStateError: pick no longer
      available in pool` 崩溃（8 人随机对局压测复现）
    - resolve_callback(picked_card_id): 释放未选选项 → create_minion →
      pending_hand_add；越界 pick 抛错（自动化 bug，禁止静默）
    - 无候选 → do() 直接 return（效果落空，同 GetRandomMinion）
    """

    def __init__(self, hero: "Hero", count: int = 3,
                 race: Optional[Race] = None,
                 min_tier: Optional[int] = None,
                 max_tier: Optional[int] = None,
                 candidates: Optional[Sequence[str]] = None,
                 kind: str = "discover_minion",
                 golden: bool = False) -> None:
        self.hero = hero
        self.count = count
        self.race = race
        self.min_tier = min_tier
        self.max_tier = max_tier
        self.candidates = candidates
        self.kind = kind
        self.golden = golden

    def do(self, game: "Game") -> None:
        if self.candidates is not None:
            # 显式候选同样受"本局可得档位"上限约束（2026-09-02 对抗审查:
            # 批量脚本自建的候选集（战吼/磁力/亡语过滤）未封顶 →
            # Discover 选项混入 Tier 7，越出标准局可得范围）。
            # 显式 min_tier=7 的 "Discover a Tier 7 minion" 族不受影响。
            # 存在档白名单（异变 101/102）: 非存在档不得出现在选项中;
            # token（tech_level 0）非酒馆档位随从，不受该白名单约束。
            cap = max(getattr(game, "max_tavern_tier", 6), self.min_tier or 0)
            ladder = getattr(game, "_tavern_tier_ladder", None)
            cands = []
            for cid in dict.fromkeys(self.candidates):
                cd = game.db.get(cid)
                if cd is not None and cd.tech_level > cap:
                    continue
                if (cd is not None and ladder is not None
                        and cd.tech_level > 0
                        and cd.tech_level not in ladder):
                    continue
                cands.append(cid)
        else:
            cands = _pool_candidates(game, self.race, self.min_tier,
                                     self.max_tier, hero=self.hero)
        if not cands:
            return
        k = min(self.count, len(cands))
        drawn = game.rng.sample(cands, k, label="discover_options")
        # 预留: 只保留真正 acquire 成功的 id（并发发现互不重叠）
        options = [cid for cid in drawn if game.minion_pool.acquire(cid)]
        if not options:
            return
        hero = self.hero
        golden = self.golden

        def resolve(pick_id: str) -> None:
            if pick_id not in options:
                raise GameStateError(
                    f"Discover: pick {pick_id} 不在提供选项中 {options}")
            for cid in options:
                if cid != pick_id:
                    game.minion_pool.release(cid, 1)
            # golden=True: 授予金色本体（独立卡定义, CARD_ID = 金卡 id,
            # TRIPLE_BASE_CARD_ID 由 create_minion 设置）。所发金色**只
            # 占池 1 份基础副本**（选项生成时 acquire 的就是 1 份），故
            # 出售/淘汰回池也必须只返 1 份——须打 GILDED_NOT_TRIPLED
            # （RULES §2.3 非三连金口径; 否则每次发现净泄漏 2 份基础
            # 副本——2026-09-02 对抗审查实测 12 → 卖后 15）
            m = game.create_minion(pick_id, controller=hero, golden=golden)
            if golden:
                m.set(GameTag.GILDED_NOT_TRIPLED, True)
            game.pending_hand_add(hero, m)

        choice = PendingChoice(
            hero, list(options), self.kind, resolve_callback=resolve)
        choice.discover_golden = bool(golden)
        game.pending_choices.append(choice)
