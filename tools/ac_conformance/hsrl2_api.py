"""hsrl2（37.0.0.255130）侧构造与驱动。

只调用引擎公开/测试同款 API（不改引擎）：
`Game(heroes, db, seed)` / `Game.run_combat` / `Game.end_recruit_phase` /
`Game.refresh_tavern` / `Game.buy_from_tavern` / `Game.sell_minion` /
`Game.upgrade_tavern` / `Minion` / `Hero`。

合成随从 = 引擎自带测试 `dummy()` 同款：`Minion(TEST_*, ..., tech_level=)`
+ `controller/zone`，直接追加到 `hero.board`；与 taverngym 侧
`edit_minion` 覆写攻/血/关键词等价（见 docs/CONFORMANCE_AUTOTAVERN.md §3）。

战斗观察字段：
* `winner`: 'a' | 'b' | 'tie'
* `capped_damage`: `CombatResult.capped_damage`（应用 turn/alive 伤害上限）
* `uncapped_damage`: `CombatResult.damage_dealt`
* `attacker_first`: `CombatResult.attacker_first`
* `rounds`: 攻击轮数；`deaths`: `game.combat_death_log` 的死亡顺序
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hsrl2.constants as C  # noqa: E402
from hsrl2.combat import CombatResult  # noqa: E402
from hsrl2.db import CardDB  # noqa: E402
from hsrl2.game import Game  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402
from hsrl2.minion import Minion  # noqa: E402
from hsrl2.tags import GameTag, Zone  # noqa: E402

DB: Optional[CardDB] = None

KW_TAGS = {
    "TAUNT": GameTag.TAUNT,
    "DIVINE_SHIELD": GameTag.DIVINE_SHIELD,
    "WINDFURY": GameTag.WINDFURY,
    "REBORN": GameTag.REBORN,
    "VENOMOUS": GameTag.VENOMOUS,
    "POISONOUS": GameTag.POISONOUS,
    "STEALTH": GameTag.STEALTH,
    "MAGNETIC": GameTag.MAGNETIC,
    "MEGA_WINDFURY": GameTag.MEGA_WINDFURY,
    "CLEAVE": GameTag.CLEAVE,
}


def db() -> CardDB:
    global DB
    if DB is None:
        DB = CardDB.load(ROOT / "data")
    return DB


def make_game(seed: int, n: int = 2) -> Game:
    heroes = [Hero(f"TEST_HERO_{i}", f"H{i}") for i in range(n)]
    return Game(heroes, db(), seed=seed)


def _new_dummy(game: Game, hero: Hero, idx: int, atk: int, hp: int,
               kws: Sequence[str], tier: int = 1) -> Minion:
    m = Minion(f"TEST_DUMMY_{idx}", f"Dummy{idx}", atk=int(atk),
               health=int(hp), tech_level=int(tier))
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    for kw in kws:
        tag = KW_TAGS.get(kw)
        if tag is None:
            raise KeyError(f"unknown keyword {kw}")
        m.set(tag, True)
    hero.board.append(m)
    return m


def _set_players(game: Game, turn: int, tier_a: int, tier_b: int) -> None:
    game.turn = int(turn)
    a, b = game.heroes[0], game.heroes[1]
    for hero, tier in ((a, tier_a), (b, tier_b)):
        hero.set(GameTag.TAVERN_TIER, int(tier))
        hero.health = 100
        hero.armor = 0


def _summon_cards(game: Game, hero: Hero, cards: Sequence[str],
                  golden: Sequence[bool] = ()) -> None:
    for i, cid in enumerate(cards):
        g = bool(golden[i]) if i < len(golden) else False
        m = game.create_minion(cid, controller=hero, golden=g)
        assert m is not None, cid
        ok = game.summon(hero, m)
        if not ok:
            raise RuntimeError(f"summon failed for {cid}")


def build_duel(seed: int, a_units=None, b_units=None, *, turn: int = 1,
               tier_a: int = 1, tier_b: int = 1, card_a=(), card_b=(),
               golden_a=(), golden_b=()):
    game = make_game(seed)
    _set_players(game, turn, tier_a, tier_b)
    a, b = game.heroes[0], game.heroes[1]
    if card_a:
        _summon_cards(game, a, card_a, golden_a)
    for i, u in enumerate(a_units or ()):
        _new_dummy(game, a, i, u["atk"], u["hp"], u.get("kws") or (),
                   u.get("tier", 1))
    if card_b:
        _summon_cards(game, b, card_b, golden_b)
    for i, u in enumerate(b_units or ()):
        _new_dummy(game, b, 100 + i, u["atk"], u["hp"], u.get("kws") or (),
                   u.get("tier", 1))
    for hero in (a, b):
        game._update_positions(hero)
    return game


def run_one(game: Game, alive: int = 8) -> Dict[str, Any]:
    """跑一场战斗，返回可观察结果（异常记为 truncated/error）。"""
    try:
        result: CombatResult = game.run_combat(
            game.heroes[0], game.heroes[1], alive_count=int(alive))
    except Exception as exc:  # noqa: BLE001 - 引擎保护上限会抛异常
        return {"error": f"{type(exc).__name__}: {exc}", "truncated": True}
    a, b = game.heroes[0], game.heroes[1]
    winner = "tie" if result.winner is None else (
        "a" if result.winner is a else "b")
    deaths = []
    for m in getattr(game, "combat_death_log", []) or []:
        deaths.append(getattr(m, "name", str(m)))
    return {
        "winner": winner,
        "capped_damage": int(result.capped_damage),
        "uncapped_damage": int(result.damage_dealt),
        "attacker_first": ("a" if result.attacker_first is a else "b")
        if result.attacker_first is not None else None,
        "rounds": int(result.rounds),
        "deaths": deaths,
        "truncated": False,
    }


def run_trials(a_units, b_units, *, seeds: int = 48, turn: int = 1,
               tier_a: int = 1, tier_b: int = 1, alive: int = 8,
               card_a=(), card_b=(), golden_a=(), golden_b=(),
               sample_seed: int = 0) -> Dict[str, Any]:
    """N 个 seed 各跑一场，返回分布 + seed0 sample 的完整观察。"""
    n = int(seeds)
    wins = {"a": 0, "b": 0, "tie": 0}
    dmg_by_winner: Dict[str, List[int]] = {"a": [], "b": []}
    attacker_first = {"a": 0, "b": 0}
    truncated = 0
    errors: List[str] = []
    sample: Optional[Dict[str, Any]] = None
    for i in range(n):
        seed = i
        game = build_duel(seed, a_units, b_units, turn=turn,
                          tier_a=tier_a, tier_b=tier_b, card_a=card_a,
                          card_b=card_b, golden_a=golden_a, golden_b=golden_b)
        obs = run_one(game, alive=alive)
        if obs.get("error"):
            errors.append(obs["error"])
            truncated += 1
            continue
        w = obs["winner"]
        wins[w] += 1
        if w in dmg_by_winner:
            dmg_by_winner[w].append(obs["capped_damage"])
        if obs["attacker_first"]:
            attacker_first[obs["attacker_first"]] += 1
        if sample is None:
            sample = obs
    return {
        "n": n,
        "wins": wins,
        "damage_by_winner": dmg_by_winner,
        "attacker_first": attacker_first,
        "truncated": truncated,
        "errors": errors,
        "sample": sample,
    }


# ══════════════════════════════════════════════════════════════════════
# 招募/经济探针
# ══════════════════════════════════════════════════════════════════════

def _drain(game: Game) -> None:
    """FIFO 解析全部 PendingChoice（choose 只结算不出队）。"""
    n = 0
    while game.pending_choices and n < 200:
        n += 1
        choice = game.pending_choices.pop(0)
        choice.choose(0)


def economy_probe(seed: int = 42) -> Dict[str, Any]:
    """记录 hsrl2 侧经济/回合常量与行为结果。"""
    game = make_game(seed, n=8)
    game.start_game()
    _drain(game)
    hero = game.heroes[0]

    gold_progression = [int(hero.gold)]
    upgrade_chain = []
    for _turn in range(2, 6):
        game.end_recruit_phase()
        _drain(game)
        gold_progression.append(int(hero.gold))

    # 价格/概率常量
    res: Dict[str, Any] = {
        "gold_progression": gold_progression,
        "start_gold": int(C.GOLD_START),
        "gold_increment": int(C.GOLD_START + 1) - int(C.GOLD_START),
        "gold_refill_cap": int(C.GOLD_INCOME_CAP),
        "buy_cost": int(C.MINION_BUY_COST),
        "sell_value": int(C.MINION_SELL_VALUE),
        "refresh_cost": int(C.REFRESH_COST),
        "board_size": int(C.BOARD_SIZE),
        "hand_size": int(C.HAND_SIZE),
        "max_regular_tier": int(C.TAVERN_MAX_TIER),
        "triple_copies": int(C.TRIPLE_COPIES_NEEDED),
        "damage_cap_until_alive": int(C.DAMAGE_CAP_REMOVED_AT_PLAYERS),
        "damage_caps": [
            [1, int(C.DAMAGE_CAP_BY_TURN)],
            [4, int(C.DAMAGE_CAP_T4_T7)],
            [8, int(C.DAMAGE_CAP_T8_PLUS)],
        ],
        "pool_copies_by_tier": [int(C.POOL_COPIES_BY_TIER[t])
                                for t in range(1, 8)],
        "spell_copies_by_tier": None,  # 见 hsrl2.pools.SpellPool
        # AutoTavern 配置含 T7 槽位；hsrl2 TAVERN_OFFERS 只到 T6（常规上限），
        # 比较时用 T6 值补齐到 7 项。
        "shop_minion_slots": [int(C.TAVERN_OFFERS[t]) for t in range(1, 7)]
        + [int(C.TAVERN_OFFERS[6])],
        "shop_spell_slots": int(C.TAVERN_SPELLS_PER_REFRESH),
        "upgrade_costs": [int(C.BASE_UPGRADE_COSTS[t]) for t in range(2, 8)],
        "upgrade_discount_per_turn": int(C.UPGRADE_DECAY_PER_TURN),
    }
    from hsrl2.pools import SpellPool
    res["spell_copies_by_tier"] = [int(SpellPool.POOL_COPIES_BY_TIER[t])
                                   for t in range(1, 7)]

    # 行为: 每 tier 免费刷新后的酒馆内容数量（随从/法术）
    shop = {}
    for tier in range(1, 7):
        hero.set(GameTag.TAVERN_TIER, tier)
        game.refresh_tavern(hero, auto=True)
        minions = sum(1 for e in hero.tavern if isinstance(e, Minion))
        spells = sum(1 for e in hero.tavern if not isinstance(e, Minion))
        shop[str(tier)] = {"minions": minions, "spells": spells}
    res["shop_by_tier"] = shop

    # 行为: 购买/出售金币增量
    hero.set(GameTag.TAVERN_TIER, 1)
    game.refresh_tavern(hero, auto=True)
    hero.gold = 10
    buy = next((e for e in hero.tavern if isinstance(e, Minion)), None)
    if buy is not None:
        g0 = int(hero.gold)
        ok = game.buy_from_tavern(hero, buy)
        res["buy_ok"] = bool(ok)
        res["buy_gold_delta"] = int(hero.gold) - g0
        if ok:
            game.play_minion(hero, buy)
            sell = buy
            g1 = int(hero.gold)
            ok2 = game.sell_minion(hero, sell)
            res["sell_ok"] = bool(ok2)
            res["sell_gold_delta"] = int(hero.gold) - g1
        else:
            res["sell_ok"] = None
            res["sell_gold_delta"] = None
    else:
        res["buy_ok"] = None
        res["buy_gold_delta"] = None
        res["sell_ok"] = None
        res["sell_gold_delta"] = None

    # 行为: 各档升级基础费用（直接读 hero.upgrade_cost；新局 turn1 未衰减）
    up = {}
    for target in range(2, 7):
        g2 = make_game(seed, n=2)
        h = g2.heroes[0]
        h.set(GameTag.TAVERN_TIER, target - 1)
        h.set(GameTag.UPGRADE_COST, C.BASE_UPGRADE_COSTS[target])
        h.gold = 99
        cost = int(h.upgrade_cost)
        ok = g2.upgrade_tavern(h)
        up[str(target)] = {
            "cost": cost,
            "ok": bool(ok),
            "gold_after": 99 - int(h.gold),   # 与 AutoTavern 探针同义：实付
            "tier_after": int(h.tavern_tier),
        }
    res["upgrade_by_tier"] = up
    res["var"] = None
    return res


def full_game_invariants(seed: int = 2000) -> Dict[str, Any]:
    """hsrl2 整局随机对局不变量（驱动方式对齐 tools/smoke_random_games.py）。"""
    from tools.smoke_random_games import play_one
    turn, finished = play_one(db(), seed, 8, 50, None)
    return {"seed": seed, "turn": int(turn), "finished": bool(finished),
            "over": bool(finished)}
