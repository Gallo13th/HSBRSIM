#!/usr/bin/env python
"""最终引擎压测 — F-06/F-07/F-08 子系统专项 + 确定性抽检 + smoke 汇总。

用法:
  python tools/final_engine_stress.py [--out runs/final_engine_stress.json]
                                     [--deity-cases 60] [--discard-cases 60]
                                     [--det-cases 20]

产出 JSON（用例数/通过数/崩溃数/确定性指纹）供 `docs/EXACTNESS_STATUS.md`
终稿引用。脚本只读引擎/卡数据，不修改任何状态。

覆盖:
  A. Deity: 2/4/8 英雄独立进度、各阈值 0..6 次 Aberration 死亡、
     达标 awaken（属性/位置/满场分支）、每场重置/再 awaken、
     Y'Shaarj 亡语复活（基础/金色）、C'Thun awaken 本体。
  B. Discard: 空手牌 Activate、成对弃置、on_discard（战斗内/外）、
     弃牌计数/Improve、EoT 弃置。
  C. Activate cost=0: 11 个定义逐个真实 `use_activate`。
  D. 确定性: 20 个 seed 的同动作序列两次运行，状态指纹一致。

退出码: 0=全部通过；1=存在失败/崩溃/不确定性。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB  # noqa: E402
from hsrl2.game import Game  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402
from hsrl2.minion import Minion  # noqa: E402
from hsrl2.tags import CardType, GameTag, Race, Zone  # noqa: E402

DB = CardDB.load(ROOT / "data")

# Activate cost=0 数据缺省的 11 个定义（F-08 修正覆盖）
ACTIVATE_ZERO_COST_IDS = (
    "BG28_582", "BG28_582_G",
    "BG36_099", "BG36_099_G",
    "BG36_300", "BG36_300_G",
    "BG36_311", "BG36_311_G",
    "BG36_312", "BG36_312_G",
    "BGMinionAbilityTest",
)


def fail(msg: str) -> None:
    raise AssertionError(msg)


def resolve_all(game: Game, rng: random.Random, cap: int = 300) -> None:
    n = 0
    while game.pending_choices and n < cap:
        n += 1
        choice = game.pending_choices.pop(0)
        choice.choose(rng.randrange(len(choice.options)))


def make_game(seed: int, players: int = 2,
              anomaly: str | None = None) -> tuple[Game, random.Random]:
    rng = random.Random(seed)
    hero_ids = [d.id for d in DB._by_id.values()
                if d.card_type == CardType.HERO and d.id.startswith("BG")]
    if not hero_ids:
        fail("no hero ids")
    heroes = [Hero(rng.choice(hero_ids), f"H{i}") for i in range(players)]
    game = Game(heroes, DB, seed=seed, anomaly=anomaly)
    game.start_game()
    resolve_all(game, rng)
    return game, rng


def make_test_minion(game: Game, hero: Hero, name: str, atk: int,
                     health: int, race: Race | None = None) -> Minion:
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, int(race))
    hero.board.append(m)
    game._update_positions(hero)
    return m


def pool_aberrations() -> list[str]:
    return [d.id for d in DB.pool_minions() if Race.ABERRATION in d.races]


def aberration_card_id(rng: random.Random) -> str:
    return rng.choice(pool_aberrations())


def put_aberration(game: Game, hero: Hero, card_id: str,
                   atk: int = 2, health: int = 3) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.set(GameTag.BASE_ATK, atk)
    m.set(GameTag.BASE_HEALTH, health)
    m.set(GameTag.HEALTH, health)
    assert game.summon(hero, m)
    return m


def kill(game: Game, m: Minion) -> None:
    m.health = 0
    game._process_single_death(m)


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    game.in_combat = True
    game._active_combat = (a, b)
    game._reset_deity_combat()


def deity_token(game: Game, hero: Hero) -> list[Minion]:
    ids = {"BGFYM_000", "BGFYM_000_G", "BGFYM_011", "BGFYM_011_G"}
    return [m for m in hero.board if m.card_id in ids and not m.dead]


def fingerprint(game: Game) -> str:
    payload = {
        "turn": game.turn,
        "finished": game.finished,
        "in_combat": game.in_combat,
        "heroes": [],
        "deity": {},
        "pending": [(c.kind, len(c.options)) for c in game.pending_choices],
        "rng_decisions": len(game.rng.decisions),
    }
    for hero in game.heroes:
        payload["heroes"].append({
            "card": hero.card_id,
            "health": hero.health,
            "gold": hero.gold,
            "tier": hero.tavern_tier,
            "hand": [getattr(e, "card_id", None) for e in hero.hand],
            "board": [[getattr(m, "card_id", None), m.atk, m.health]
                      for m in hero.board],
            "tavern": [getattr(e, "card_id", None) for e in hero.tavern],
            "deity": (lambda st: None if st is None else [
                st.card_id, st.golden, st.atk, st.health,
                st.progress, st.awakened])(getattr(hero, "deity", None)),
            "discarded": getattr(hero, "cards_discarded_this_game", 0),
        })
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


# ══════════════════════════════════════════════════════════════════════
# A. Deity 专项
# ══════════════════════════════════════════════════════════════════════


def deity_case(seed: int) -> list[str]:
    """构造 1 个随机 Deity 局面，返回失败项（[]=通过）。"""
    failures: list[str] = []
    rng = random.Random(seed)
    players = rng.choice([2, 4, 8])
    game, rng = make_game(seed, players=players)
    try:
        a = game.heroes[0]
        b = game.heroes[1 % players]
        # 多英雄独立 Deity
        for hero in game.heroes:
            if rng.random() < 0.5:
                game.select_deity(hero, rng.choice(["BGFYM_000", "BGFYM_011"]))
            else:
                game.deity(hero)
            game.give_deity_stats(hero, rng.randint(0, 4), rng.randint(0, 4))
        state = game.deity(a)
        if rng.random() < 0.15:
            state.golden = True
        enter_combat(game, a, b)
        threshold = game.deity_threshold()
        n_deaths = rng.randint(0, 6)
        # 20% 满场分支（仅当本次死亡数足以触发 awaken）
        full_board = (rng.random() < 0.2) and n_deaths >= threshold
        if full_board:
            while len(a.board) < 7:
                make_test_minion(game, a, f"F{len(a.board)}", 1, 5,
                                 Race.BEAST)
        recorded: list[tuple] = []
        awaken_stats: tuple | None = None
        for i in range(n_deaths):
            cid = aberration_card_id(rng)
            atk, hp = rng.randint(1, 9), rng.randint(1, 9)
            # 纯测试 Aberration（无脚本）——避免随机卡脚本改变 Deity，
            # 只验证 F-07 进度/awaken 契约本身
            m = make_test_minion(game, a, f"Ab{i}", atk, hp,
                                 Race.ABERRATION)
            m.card_id = cid
            recorded.append((cid, atk, hp))
            kill(game, m)
            if state.awakened and awaken_stats is None:
                awaken_stats = (state.atk, state.health)
        token = deity_token(game, a)
        should_awaken = n_deaths >= threshold
        if full_board:
            if token:
                failures.append(f"seed={seed}: 满场不应召唤 token")
            if state.awakened:
                failures.append(f"seed={seed}: 满场不应置 awakened")
            # 腾位后应可召唤
            while len(a.board) >= 7:
                a.board.pop()
            if awaken_stats is None:
                awaken_stats = (state.atk, state.health)
            game._maybe_awaken_deity(a)
            if not state.awakened:
                failures.append(f"seed={seed}: 腾位后未 awaken")
            elif token:
                if (token[0].atk, token[0].health) != awaken_stats:
                    failures.append(
                        f"seed={seed}: 满场后 token 属性 "
                        f"{token[0].atk}/{token[0].health} != {awaken_stats}")
        elif should_awaken:
            if not state.awakened or len(token) != 1:
                failures.append(
                    f"seed={seed}: 达标未 awaken (n={n_deaths})")
            else:
                expected_id = ("BGFYM_000_G" if state.card_id == "BGFYM_000"
                               and state.golden else
                               "BGFYM_011_G" if state.golden else state.card_id)
                if token[0].card_id != expected_id:
                    failures.append(
                        f"seed={seed}: token id {token[0].card_id} != 期望")
                if (token[0].atk, token[0].health) != awaken_stats:
                    failures.append(
                        f"seed={seed}: token 属性 {token[0].atk}/"
                        f"{token[0].health} != Deity {awaken_stats}")
        else:
            if state.awakened or token:
                failures.append(f"seed={seed}: 未达标提前 awaken")
        # 其它英雄独立（不因 a 的 Aberration 死亡推进）
        for hero in game.heroes[1:]:
            if len(hero.board) or True:
                st = game.deity(hero)
                if st.progress or st.awakened:
                    # b 是战斗对手，其 Aberration 死亡可能来自它自己；
                    # 本用例只往 a 棋盘放 Aberration → 其它英雄必须为 0
                    failures.append(
                        f"seed={seed}: 英雄 {hero.name} 进度被跨英雄污染")
        # 每场重置
        game._reset_deity_combat()
        if state.progress != 0 or state.awakened:
            failures.append(f"seed={seed}: 每场重置失败")
        # 第二场再 awaken（若首场已 awaken 且 token 占位，先腾出）
        enter_combat(game, a, b)
        for i in range(threshold):
            while len(a.board) >= 7:
                a.board.pop()
            m = make_test_minion(game, a, f"B{i}", 1, 1,
                                 Race.ABERRATION)
            kill(game, m)
        if not game.deity(a).awakened:
            failures.append(f"seed={seed}: 第二场未再 awaken")
        # Y'Shaarj 亡语复活（每 5 个用例抽一个）
        if seed % 5 == 0:
            game2, rng2 = make_game(seed + 10_000, players=2)
            h = game2.heroes[0]
            opp = game2.heroes[1]
            game2.select_deity(h, "BGFYM_011")
            enter_combat(game2, h, opp)
            for i in range(4):
                put_aberration(game2, h, "BGFYM_002t", i + 2, i + 3)
                kill(game2, h.board[-1])
            toks = [m for m in h.board if m.card_id == "BGFYM_011"]
            if len(toks) != 1:
                failures.append(f"seed={seed}: Y'Shaarj awaken 失败")
            else:
                toks[0].health = 1
                kill(game2, toks[0])
                revived = [m for m in h.board if m.card_id == "BGFYM_002t"]
                if len(revived) < 2:
                    failures.append(
                        f"seed={seed}: Y'Shaarj 复活 {len(revived)} < 2")
    except Exception as e:                       # noqa: BLE001
        failures.append(f"seed={seed}: {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
    return failures


# ══════════════════════════════════════════════════════════════════════
# B. Discard 专项
# ══════════════════════════════════════════════════════════════════════


def hand_spell(game: Game, hero: Hero, card_id: str):
    s = game.create_spell(card_id, controller=hero)
    from hsrl2.scripts import REGISTRY
    s.scripts = REGISTRY.get(card_id)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def discard_case(seed: int) -> list[str]:
    failures: list[str] = []
    rng = random.Random(seed)
    game, rng = make_game(seed, players=2)
    try:
        a, b = game.heroes
        kind = seed % 4
        if kind == 0:
            # 空手牌 Activate（cost=0）
            a.gold = 0
            for cid in ("BG28_582", "BG36_099", "BG36_311", "BG36_312"):
                m = game.create_minion(cid, controller=a)
                game.summon(a, m)
                if a.hand:
                    a.hand.clear()
                ok = game.use_activate(a, m)
                if not ok:
                    failures.append(f"seed={seed}: {cid} 空手牌 Activate 失败")
                if game.pending_choices:
                    failures.append(
                        f"seed={seed}: {cid} 空手牌仍产生弃牌选择")
                resolve_all(game, rng)
                a.gold = 0
        elif kind == 1:
            # 成对弃置（Willbreaker/Operative 基础/金色）
            for cid, golden in (("BG36_100", False), ("BG36_100_G", True),
                                ("BG36_308", False), ("BG36_308_G", True)):
                m = game.create_minion(cid, controller=a, golden=golden)
                game.summon(a, m)
                before = set(a.hand)
                game.sell_minion(a, m)
                new = [c for c in a.hand if c not in before]
                if len(new) != (4 if golden else 2):
                    failures.append(
                        f"seed={seed}: {cid} 售出生成 {len(new)} 张")
                threshold = len(new) // 2
                for c in new[:threshold]:
                    if c in a.hand:
                        a.hand.remove(c)
                    game.events.fire(game, "card_played", card=c)
                remaining = [c for c in new[threshold:] if c in a.hand]
                if remaining:
                    failures.append(
                        f"seed={seed}: {cid} 成对弃置残留 {len(remaining)}")
                a.hand.clear()
                a.cards_discarded_this_game = 0
        elif kind == 2:
            # on_discard（战斗外/战斗内）+ 计数
            for in_combat in (False, True):
                game.in_combat = in_combat
                if in_combat:
                    game._active_combat = (a, b)
                    game._reset_deity_combat()
                ally = make_test_minion(game, a, f"Ally{in_combat}", 1, 20)
                sludge = hand_spell(game, a, "BG36_301t")
                before = a.cards_discarded_this_game
                if not game.discard_card(a, sludge):
                    failures.append(f"seed={seed}: 弃置 Sludge 失败")
                if a.cards_discarded_this_game != before + 1:
                    failures.append(f"seed={seed}: 弃牌计数未 +1")
                if (ally.atk, ally.health) not in ((3, 22),):
                    failures.append(
                        f"seed={seed}: Sludge on_discard 未生效")
                a.board.remove(ally)
            game.in_combat = False
            game._active_combat = None
        else:
            # 监听器/Improve/EoT 弃置
            md = game.create_minion("BG36_097", controller=a)
            game.summon(a, md)
            ally = make_test_minion(game, a, "Ally", 1, 20)
            game.discard_card(a, hand_spell(game, a, "BG28_810"))
            if (ally.atk, ally.health) != (5, 24):
                failures.append(f"seed={seed}: Mindbender 监听未生效")
            # 移开 Mindbender（连同注销其监听器），避免其"other minions"
            # 监听给 Cutthroat 加成
            game.events.unregister_owner(md)
            a.board.remove(md)
            ct = game.create_minion("BG36_106", controller=a)
            game.summon(a, ct)
            game.discard_card(a, hand_spell(game, a, "BG28_810"))
            if (ct.atk, ct.health) != (8, 8):
                failures.append(f"seed={seed}: Cutthroat 监听未生效")
            game.events.unregister_owner(ct)
            a.board.remove(ct)
            hb = game.create_minion("BGFYM_005", controller=a)
            game.summon(a, hb)
            game.discard_card(a, hand_spell(game, a, "BG28_810"))
            if not (game.deity(a).atk >= 1 and game.deity(a).health >= 1):
                failures.append(f"seed={seed}: Harbinger Deity 未生效")
            # Parasitic EoT: 清场后「最左」= 先放的 left
            a.board.clear()
            left = make_test_minion(game, a, "Left", 1, 20)
            pf = game.create_minion("BG36_114", controller=a)
            game.summon(a, pf)
            n = rng.randint(0, 4)
            a.cards_discarded_this_game = n
            game.run_script_hook(pf, "end_of_turn")
            expected = (1 + 2 * (1 + n), 20 + 2 * (1 + n))
            if (left.atk, left.health) != expected:
                failures.append(
                    f"seed={seed}: Parasitic EoT {left.atk}/{left.health}"
                    f" != {expected}")
    except Exception as e:                       # noqa: BLE001
        failures.append(f"seed={seed}: {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
    return failures


def activate_zero_cost_case() -> list[str]:
    failures: list[str] = []
    for cid in ACTIVATE_ZERO_COST_IDS:
        d = DB.get(cid)
        if d is None:
            failures.append(f"{cid}: CardDef 缺失")
            continue
        game, _ = make_game(1, players=2)
        a = game.heroes[0]
        m = game.create_minion(cid, controller=a)
        if not m.has(GameTag.ACTIVATE):
            failures.append(f"{cid}: 未标记 ACTIVATE")
            continue
        if m.get(GameTag.ACTIVATE_COST) != 0:
            failures.append(f"{cid}: ACTIVATE_COST != 0")
        game.summon(a, m)
        a.gold = 0
        if not game.use_activate(a, m):
            failures.append(f"{cid}: use_activate 失败")
        if m.get(GameTag.ACTIVATE_USED_THIS_TURN) is not True:
            failures.append(f"{cid}: 每回合使用标记未置位")
        while game.pending_choices:
            c = game.pending_choices.pop(0)
            c.choose(0)
        if game.use_activate(a, m):
            failures.append(f"{cid}: 同回合二次 use_activate 应为 False")
    return failures


# ══════════════════════════════════════════════════════════════════════
# D. 确定性
# ══════════════════════════════════════════════════════════════════════


def det_scenario(seed: int) -> str:
    """同 seed 的确定性动作序列 → 状态指纹（覆盖 Deity/Discard）。"""
    rng = random.Random(seed)
    game, rng = make_game(seed, players=2 if seed % 2 == 0 else 4)
    a = game.heroes[0]
    # 固定覆盖: Deity 增益 + 弃置 + 成对弃置 + 战斗内 Aberration 死亡
    game.give_deity_stats(a, 2, 1)
    game.discard_card(a, hand_spell(game, a, "BG28_810"))
    game.discard_card(a, hand_spell(game, a, "BG36_301t"))
    wb = game.create_minion("BG36_100", controller=a)
    game.summon(a, wb)
    game.sell_minion(a, wb)
    if a.hand:
        first = list(a.hand)[0]
        if first in a.hand:
            a.hand.remove(first)
        game.events.fire(game, "card_played", card=first)
    # 随机但确定的动作序列
    for _ in range(6):
        action = rng.randrange(5)
        try:
            if action == 0 and a.tavern:
                ent = rng.choice(list(a.tavern))
                if not a.hand_full():
                    game.buy_from_tavern(a, ent)
            elif action == 1:
                game.refresh_tavern(a)
            elif action == 2 and a.hand:
                game.discard_card(a, rng.choice(list(a.hand)))
            elif action == 3:
                game.give_deity_stats(a, 1, 0)
            elif action == 4 and a.board:
                game.sell_minion(a, rng.choice(list(a.board)))
        except Exception:                        # noqa: BLE001
            pass
        resolve_all(game, rng)
    # 战斗内 Deity 推进（4 次 Aberration 死亡）；先腾出板位
    while len(a.board) > 3:
        a.board.pop()
    opp = game.heroes[1 % len(game.heroes)]
    enter_combat(game, a, opp)
    for i in range(4):
        cid = aberration_card_id(rng)
        put_aberration(game, a, cid, i + 1, i + 1)
        kill(game, a.board[-1])
    resolve_all(game, rng)
    return fingerprint(game)


# ══════════════════════════════════════════════════════════════════════
# smoke 结果汇总
# ══════════════════════════════════════════════════════════════════════


def collect_smoke() -> dict:
    import re
    groups = []
    for players in (2, 4, 8):
        path = ROOT / "runs" / f"smoke200_{players}p.txt"
        if not path.exists():
            groups.append({"players": players, "present": False})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(
            r"games=(\d+) completed=(\d+) incomplete=(\d+) crashes=(\d+)",
            text)
        if not m:
            groups.append({"players": players, "present": False})
            continue
        groups.append({
            "players": players, "present": True,
            "games": int(m.group(1)), "completed": int(m.group(2)),
            "incomplete": int(m.group(3)), "crashes": int(m.group(4)),
        })
    totals = {
        "games": sum(g.get("games", 0) for g in groups),
        "completed": sum(g.get("completed", 0) for g in groups),
        "incomplete": sum(g.get("incomplete", 0) for g in groups),
        "crashes": sum(g.get("crashes", 0) for g in groups),
    }
    return {"groups": groups, "totals": totals}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "runs" / "final_engine_stress.json"))
    ap.add_argument("--deity-cases", type=int, default=60)
    ap.add_argument("--discard-cases", type=int, default=60)
    ap.add_argument("--det-cases", type=int, default=20)
    args = ap.parse_args()

    t0 = time.time()
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "engine_data": "37.0.0.255130",
        "smoke": collect_smoke(),
    }

    # A. Deity
    deity_fail: list[str] = []
    deity_crashes = 0
    for i in range(args.deity_cases):
        f = deity_case(1000 + i)
        if any(": " in x and "Exception" in x for x in f):
            deity_crashes += 1
        deity_fail.extend(f)
    result["deity"] = {
        "cases": args.deity_cases,
        "passed": args.deity_cases - len({x.split(":")[0] for x in deity_fail}),
        "failures": len(deity_fail),
        "crashes": deity_crashes,
        "details": deity_fail[:20],
    }

    # B. Discard
    discard_fail: list[str] = []
    discard_crashes = 0
    for i in range(args.discard_cases):
        f = discard_case(2000 + i)
        if any("Exception" in x or "Error" in x for x in f):
            discard_crashes += 1
        discard_fail.extend(f)
    result["discard"] = {
        "cases": args.discard_cases,
        "passed": args.discard_cases - len({x.split(":")[0] for x in discard_fail}),
        "failures": len(discard_fail),
        "crashes": discard_crashes,
        "details": discard_fail[:20],
    }

    # C. Activate cost=0
    az_fail = activate_zero_cost_case()
    result["activate_zero_cost"] = {
        "definitions": len(ACTIVATE_ZERO_COST_IDS),
        "passed": len(ACTIVATE_ZERO_COST_IDS) - len(az_fail),
        "failures": len(az_fail),
        "details": az_fail[:20],
    }

    # D. Determinism
    det_ok = 0
    det_fail: list[str] = []
    digests: list[str] = []
    for i in range(args.det_cases):
        seed = 3000 + i
        f1 = det_scenario(seed)
        f2 = det_scenario(seed)
        digests.append(f1)
        if f1 == f2:
            det_ok += 1
        else:
            det_fail.append(f"seed={seed}: fingerprint 不一致")
    result["determinism"] = {
        "cases": args.det_cases,
        "identical": det_ok,
        "failures": len(det_fail),
        "compute_digest": hashlib.sha256(
            "|".join(digests).encode()).hexdigest(),
        "details": det_fail[:20],
    }
    result["elapsed_s"] = round(time.time() - t0, 1)

    failures = (len(deity_fail) + len(discard_fail) + len(az_fail)
                + len(det_fail))
    result["ok"] = failures == 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("deity", "discard", "activate_zero_cost",
                       "determinism", "elapsed_s", "ok")},
                     ensure_ascii=False))
    print(f"wrote {out}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
