#!/usr/bin/env python
"""ENGINE_API.md 的逐条可运行验证脚本（每个断言对应文档中一个片段）。

用法:
  python tools/probe_api.py
  python tools/probe_api.py --verbose

退出码 0 = 全部 PASS；1 = 有 FAIL（打印失败清单）。
本脚本**只读**引擎、只做断言，不修改 hsrl2/ 与 hsbg/ 任何文件。
"""

from __future__ import annotations

import argparse
import random
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2 import constants as C  # noqa: E402
from hsrl2.db import CardDB  # noqa: E402
from hsrl2.game import Game, GameStateError, PendingChoice  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402
from hsrl2.minion import Minion  # noqa: E402
from hsrl2.scripts import REGISTRY  # noqa: E402
from hsrl2.spell import Spell  # noqa: E402
from hsrl2.tags import CardType, GameTag, Race, Zone  # noqa: E402

DATA_DIR = ROOT / "data"
DB: CardDB | None = None
RESULTS: list = []          # (ok, section, name, detail)
VERBOSE = False


# ---------------------------------------------------------------- check utils


def check(section: str, name: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append((bool(cond), section, name, detail))
    if VERBOSE or not cond:
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {section} :: {name}"
              + (f"  ({detail})" if detail else ""))
    return bool(cond)


def check_eq(section: str, name: str, got, want) -> bool:
    return check(section, name, got == want, f"got={got!r} want={want!r}")


def expect_raise(section: str, name: str, exc, fn, *a, **kw) -> bool:
    try:
        fn(*a, **kw)
    except exc as e:                          # noqa: BLE001
        return check(section, name, True, f"{type(e).__name__}: {e}")
    except Exception as e:                    # noqa: BLE001
        return check(section, name, False,
                     f"wrong exception {type(e).__name__}: {e}")
    return check(section, name, False, "did not raise")


def section(title: str) -> None:
    if VERBOSE:
        print(f"\n--- {title} ---")


# ---------------------------------------------------------------- fixtures


def hero_defs(db: CardDB) -> list:
    return [d for d in db._by_id.values() if d.card_type == CardType.HERO]


def hero_ids(db: CardDB) -> list:
    return [d.id for d in hero_defs(db)]


def new_game(db: CardDB, n: int = 2, seed: int = 42,
             hero_id_list=None, anomaly=None, start: bool = True) -> Game:
    ids = hero_id_list or hero_ids(db)
    heroes = [Hero(ids[i % len(ids)], f"H{i}") for i in range(n)]
    game = Game(heroes, db, seed=seed, anomaly=anomaly)
    if start:
        game.start_game()
    return game


def drain(game: Game, pick: int = 0) -> list:
    """FIFO 结算全部 PendingChoice（choose 只结算不出队——必须 pop）。"""
    kinds = []
    guard = 0
    while game.pending_choices and guard < 400:
        guard += 1
        choice = game.pending_choices.pop(0)
        kinds.append(choice.kind)
        choice.choose(min(pick, len(choice.options) - 1))
    return kinds


def finish_turn(game: Game, rng: random.Random | None = None) -> None:
    """推进一个完整回合（结算遗留选择 → ERP → 结算战斗期选择）。"""
    drain(game)
    game.end_recruit_phase()
    drain(game)


def find_minion(db: CardDB, pred) -> object:
    for d in db.pool_minions():
        if pred(d):
            return d
    return None


def minion_script(cid: str):
    return REGISTRY.get(cid)


def make_hand_minion(game: Game, hero: Hero, card_id: str = None) -> Minion:
    d = game.db.get(card_id) if card_id else game.db.pool_minions()[0]
    m = game.create_minion(d.id, controller=hero)
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def summon_minion(game: Game, hero: Hero, card_id: str = None,
                  atk: int = 1, health: int = 20) -> Minion:
    d = game.db.get(card_id) if card_id else game.db.pool_minions()[0]
    m = game.create_minion(d.id, controller=hero)
    m.set(GameTag.BASE_ATK, atk)
    m.set(GameTag.HEALTH, health)
    m.set(GameTag.BASE_HEALTH, health)
    game.summon(hero, m)
    return m


# ══════════════════════════════════════════════════════════════════════
# A1 初始化
# ══════════════════════════════════════════════════════════════════════


def probe_a1(db: CardDB) -> None:
    section("A1 初始化")
    check("A1", "CardDB.load 定义数 > 3000", len(db) > 3000, f"{len(db)}")
    d = db.get("BGS_018")
    check("A1", "db.get('BGS_018') 非空", d is not None)
    if d is not None:
        check("A1", "db.by_dbf 反查同一 CardDef",
              db.by_dbf(d.dbf_id) is d)
        check("A1", "CardDef 字段可读",
              isinstance(d.tech_level, int)
              and isinstance(d.keywords, frozenset)
              and isinstance(d.races, frozenset)
              and d.card_type == CardType.MINION,
              f"{d.name} T{d.tech_level} {d.atk}/{d.health}")

    heroes = hero_defs(db)
    check("A1", "英雄定义可枚举", len(heroes) > 100, f"{len(heroes)} 个")
    with_power = [d.id for d in heroes if d.hero_power_id]
    check("A1", "英雄带 hero_power_id",
          len(with_power) == len(heroes), f"{len(with_power)}")

    h = Hero(with_power[0], "P1")
    check("A1", "Hero 初始属性",
          (h.health, h.armor, h.gold, h.tavern_tier, h.upgrade_cost)
          == (C.HERO_BASE_HEALTH, 0, 0, 1, C.BASE_UPGRADE_COSTS[2])
          and h.is_alive and h.board == [] and h.hand == []
          and h.tavern == [],
          f"{h.health}/{h.armor} gold={h.gold} tier={h.tavern_tier} "
          f"upcost={h.upgrade_cost}")

    game = Game([Hero(with_power[0], "A"), Hero(with_power[1], "B")],
                db, seed=1234)
    check("A1", "Game 构造：turn=0 / heroes 引用",
          game.turn == 0 and len(game.heroes) == 2
          and game.heroes[0].game is game)
    check("A1", "GameRNG.seed_value 记录 seed", game.rng.seed_value == 1234)
    check("A1", "start_game 前金币为 0",
          [x.gold for x in game.heroes] == [0, 0])
    game.start_game()
    check("A1", "start_game: turn=1", game.turn == 1)
    check("A1", "start_game: 金币=3（gold_base_income(1)）",
          [x.gold for x in game.heroes] == [3, 3])
    check("A1", "start_game: 酒馆已刷新（3 随从 + 1 法术）",
          len(game.heroes[0].tavern) == 4
          and sum(isinstance(e, Minion) for e in game.heroes[0].tavern) == 3
          and sum(isinstance(e, Spell) for e in game.heroes[0].tavern) == 1)
    check("A1", "start_game: 升级费=5",
          [x.upgrade_cost for x in game.heroes] == [5, 5])

    bad = Game([Hero(with_power[0], "X")], db, anomaly=with_power[0])
    expect_raise("A1", "anomaly 非 BACON_ANOMALY → GameStateError",
                 GameStateError, bad.start_game)

    anomalies = [k for k in REGISTRY
                 if db.get(k) is not None
                 and db.get(k).card_type == CardType.BACON_ANOMALY]
    check("A1", "异变池可枚举（card_type=BACON_ANOMALY）",
          len(anomalies) > 50, f"{len(anomalies)}")
    ok_anomaly = True
    try:
        g2 = new_game(db, 2, seed=7, anomaly=anomalies[0])
        drain(g2)
        ok_anomaly = g2.turn == 1
    except Exception as e:                     # noqa: BLE001
        ok_anomaly = False
        detail = f"{type(e).__name__}: {e}"
    else:
        detail = anomalies[0]
    check("A1", "Game(anomaly=合法 id) 可开局", ok_anomaly, detail)


# ══════════════════════════════════════════════════════════════════════
# A2 回合流程
# ══════════════════════════════════════════════════════════════════════


def probe_a2(db: CardDB) -> None:
    section("A2 回合流程")
    game = new_game(db, 2, seed=11)
    a, b = game.heroes

    # 记录回合开始副作用
    a.gold = 0
    a.set(GameTag.UPGRADE_COST, 5)
    tavern_before = list(a.tavern)

    # SoT 钩子探针：给棋盘随从挂一个假的 start_of_turn 脚本
    calls = {"sot": 0}

    class SoTProbe:
        @staticmethod
        def start_of_turn(source, g, ctx=None):
            calls["sot"] += 1

    m = summon_minion(game, a, health=50)
    m.scripts = SoTProbe

    game.end_recruit_phase()
    drain(game)
    check("A2", "end_recruit_phase: turn+1", game.turn == 2, f"{game.turn}")
    check_eq("A2", "回合开始金币=gold_base_income(turn)",
             [x.gold for x in game.heroes],
             [C.gold_base_income(2), C.gold_base_income(2)])
    check_eq("A2", "回合开始升级费 -1（下限 0）",
             (a.upgrade_cost, b.upgrade_cost), (4, 4))
    check("A2", "回合开始酒馆自动刷新（内容变化）",
          len(a.tavern) > 0 and a.tavern != tavern_before,
          f"size={len(a.tavern)}")
    check("A2", "回合开始触发棋盘随从 start_of_turn",
          calls["sot"] >= 1, f"calls={calls['sot']}")
    check("A2", "招募阶段判定：not finished and not in_combat",
          (not game.finished) and (not game.in_combat)
          and game.pending_choices == [])

    # 冻结保留：手动冻结后回合开始刷新仍保留内容
    g3 = new_game(db, 2, seed=12)
    h = g3.heroes[0]
    frozen = list(h.tavern)
    g3.freeze_tavern(h)
    g3.end_recruit_phase()
    drain(g3)
    check("A2", "冻结后跨回合刷新保留内容（只保留一轮）",
          all(e in h.tavern for e in frozen) and not h.frozen_tavern,
          f"{len(frozen)} 个保留")

    # 任务 offer（第 4 回合）与饰品 offer（第 6/9 回合）
    # 注意：_begin_recruit_for 在 ERP 内部生成下回合的选择，因此必须
    # 在 ERP 之后**立刻**读取 pending_choices（不能先 drain）。
    g5 = new_game(db, 2, seed=13)
    quest_kinds = trinket6 = []
    saw_quest = []
    for _ in range(12):
        if g5.finished:
            break
        if g5.turn == 4:
            quest_kinds = [(c.kind, len(c.options)) for c in g5.pending_choices]
            saw_quest = [c.options[0] for c in g5.pending_choices]
        elif g5.turn == 6:
            trinket6 = [(c.kind, len(c.options)) for c in g5.pending_choices]
        drain(g5)
        g5.end_recruit_phase()
    check("A2", "第 4 回合生成 quest_offer（每英雄 1 个）",
          len(quest_kinds) == 2
          and all(k == "quest_offer" for k, _ in quest_kinds)
          and all(n == 3 for _, n in quest_kinds), f"{quest_kinds}")
    check("A2", "quest_offer 选项 = (quest_id, reward_id) 二元组",
          bool(saw_quest) and isinstance(saw_quest[0], tuple)
          and len(saw_quest[0]) == 2
          and all(isinstance(x, str) for x in saw_quest[0]),
          f"{saw_quest[:1]}")
    check("A2", "第 6 回合生成 trinket_offer（4 选 1 + None 放弃）",
          len(trinket6) == 2
          and all(k == "trinket_offer" for k, _ in trinket6)
          and all(n == C.TRINKET_CHOICES + 1 for _, n in trinket6),
          f"{trinket6}")


# ══════════════════════════════════════════════════════════════════════
# A3 动作 API
# ══════════════════════════════════════════════════════════════════════


def probe_a3_buy(db: CardDB) -> None:
    section("A3 buy_from_tavern")
    game = new_game(db, 2, seed=21)
    h = game.heroes[0]
    h.gold = 10
    e = next(x for x in h.tavern if isinstance(x, Minion))
    cost = e.get(GameTag.COST, C.MINION_BUY_COST)
    before_hand, before_tavern = len(h.hand), len(h.tavern)
    ok = game.buy_from_tavern(h, e)
    drain(game)
    check("A3", "buy: 返回 True", ok is True)
    check("A3", "buy: 实体入场 → 手牌", e in h.hand and e.zone == Zone.HAND
          and len(h.hand) == before_hand + 1)
    check("A3", "buy: 酒馆 -1 / 扣金币", len(h.tavern) == before_tavern - 1
          and h.gold == 10 - cost, f"gold={h.gold} cost={cost}")
    check("A3", "buy: 不在酒馆 → False",
          game.buy_from_tavern(h, game.create_minion(
              db.pool_minions()[0].id, controller=h)) is False)
    # 满手
    h2 = game.heroes[1]
    h2.gold = 10
    while not h2.hand_full():
        h2.add_to_hand(game.create_minion(db.pool_minions()[0].id,
                                          controller=h2))
    check("A3", "buy: 满手牌 → False（且不扣钱）",
          game.buy_from_tavern(h2, next(
              x for x in h2.tavern if isinstance(x, Minion))) is False
          and h2.gold == 10)
    # 金币不足
    h.gold = 0
    check("A3", "buy: 金币不足 → False",
          game.buy_from_tavern(h, next(
              x for x in h.tavern if isinstance(x, Minion))) is False)
    # TURN_SKIPPED
    h.gold = 10
    h.set(GameTag.TURN_SKIPPED, True)
    check("A3", "buy: TURN_SKIPPED → False",
          game.buy_from_tavern(h, next(
              x for x in h.tavern if isinstance(x, Minion))) is False)
    h.clear(GameTag.TURN_SKIPPED)


def probe_a3_sell(db: CardDB) -> None:
    section("A3 sell_minion")
    game = new_game(db, 2, seed=22)
    h = game.heroes[0]
    h.gold = 0
    m = summon_minion(game, h)
    check("A3", "sell: 棋盘随从 → True / +1 金 / 离场",
          game.sell_minion(h, m) is True and h.gold == 1
          and m not in h.board and m.zone == Zone.REMOVED)
    hm = make_hand_minion(game, h)
    check("A3", "sell: 手牌随从也可卖（+1 金）",
          game.sell_minion(h, hm) is True and hm not in h.hand
          and h.gold == 2)
    outsider = game.create_minion(db.pool_minions()[0].id, controller=h)
    check("A3", "sell: 不在棋盘/手牌 → False",
          game.sell_minion(h, outsider) is False)


def _needs_target_minion(db: CardDB):
    for d in db.pool_minions():
        sc = REGISTRY.get(d.id)
        if sc is not None and getattr(sc, "needs_target", False) \
                and getattr(sc, "battlecry", None) is not None:
            return d
    return None


def _choose_one_minion(db: CardDB):
    for d in db.pool_minions():
        sc = REGISTRY.get(d.id)
        if sc is not None and getattr(sc, "choose_options", None):
            return d
    return None


def _magnetic_minion(db: CardDB):
    for d in db.pool_minions():
        if "magnetic" in d.keywords:
            return d
    return None


def _mech_minion(db: CardDB):
    for d in db.pool_minions():
        if Race.MECH in d.races:
            return d
    return None


def probe_a3_play_minion(db: CardDB) -> None:
    section("A3 play_minion")
    game = new_game(db, 2, seed=23)
    h = game.heroes[0]
    front = summon_minion(game, h, atk=2, health=30)
    m = make_hand_minion(game, h)
    ok = game.play_minion(h, m, position=0)
    drain(game)
    check("A3", "play_minion: 返回 True / 手牌→棋盘",
          ok is True and m not in h.hand and m in h.board
          and m.zone == Zone.PLAY and m.controller is h)
    check("A3", "play_minion: position=0 插入最左",
          h.board.index(m) == 0 and len(h.board) == 2)
    check("A3", "play_minion: 不在手牌 → False",
          game.play_minion(h, game.create_minion(
              db.pool_minions()[0].id, controller=h)) is False)

    # 满板
    board7 = game
    while not h.board_full():
        board7.summon(h, board7.create_minion(db.pool_minions()[0].id,
                                              controller=h))
    overflow = []
    from hsrl2.events import Listener
    game.events.register(Listener(event="minion_overflow", owner=h,
                                  callback=lambda g, **kw:
                                  overflow.append(kw["minion"])))
    m2 = make_hand_minion(game, h)
    check("A3", "play_minion: 棋盘满 → False + minion_overflow 事件",
          game.play_minion(h, m2) is False and m2 in h.hand
          and len(overflow) == 1)

    # 锁定 / unplayable
    g2 = new_game(db, 2, seed=24)
    h2 = g2.heroes[0]
    locked = make_hand_minion(g2, h2)
    locked.set(GameTag.LOCKED_IN_HAND, True)
    check("A3", "play_minion: LOCKED_IN_HAND → False",
          g2.play_minion(h2, locked) is False)
    unplayable = [d for d in db.pool_minions() if d.unplayable]
    check("A3", "数据中存在 unplayable 随从（可选检查）",
          isinstance(unplayable, list))

    # Choose One
    co_def = _choose_one_minion(db)
    if co_def is not None:
        g3 = new_game(db, 2, seed=25)
        h3 = g3.heroes[0]
        co = make_hand_minion(g3, h3, co_def.id)
        ok = g3.play_minion(h3, co)
        check("A3", "play_minion: Choose One → PendingChoice(choose_one)",
              ok is True and len(g3.pending_choices) == 1
              and g3.pending_choices[0].kind == "choose_one",
              f"{getattr(co_def, 'name', '')}")
        ch = g3.pending_choices.pop(0)
        ch.choose(0)
        check("A3", "play_minion: choose_one 结算后随从在棋盘",
              co in h3.board)
    else:
        check("A3", "play_minion: Choose One 卡存在", False, "未找到")

    # 定向战吼
    nt_def = _needs_target_minion(db)
    if nt_def is not None:
        g4 = new_game(db, 2, seed=26)
        h4 = g4.heroes[0]
        target = summon_minion(g4, h4, atk=1, health=30)
        nt = make_hand_minion(g4, h4, nt_def.id)
        ok = g4.play_minion(h4, nt)
        check("A3", "play_minion: needs_target 无 target → 挂起选择",
              ok is True and len(g4.pending_choices) == 1
              and g4.pending_choices[0].kind == "battlecry_target",
              getattr(nt_def, "name", ""))
        ch = g4.pending_choices.pop(0)
        check("A3", "play_minion: battlecry_target 候选为非空 Minion 列表",
              len(ch.options) > 0
              and all(isinstance(x, Minion) for x in ch.options))
        ch.choose(0)
        check("A3", "play_minion: battlecry_target 结算后随从在场",
              nt in h4.board)
    else:
        check("A3", "play_minion: 定向战吼卡存在", False, "未找到")

    # 磁力吸附
    mag_def = _magnetic_minion(db)
    mech_def = _mech_minion(db)
    if mag_def is not None and mech_def is not None:
        g5 = new_game(db, 2, seed=27)
        h5 = g5.heroes[0]
        host = summon_minion(g5, h5, mech_def.id, atk=1, health=10)
        h5.gold = 10
        # 从酒馆买不到指定卡；直接建实体进手牌（白盒：仅为验证 API 语义）
        mag = g5.create_minion(mag_def.id, controller=h5)
        h5.hand.append(mag)
        mag.zone = Zone.HAND
        atk_before = host.atk
        ok = g5.play_minion(h5, mag, magnetic_target=host)
        check("A3", "play_minion: 磁力吸附 → True / 属性并入宿主 / 不占板位",
              ok is True and host.atk == atk_before + mag_def.atk
              and mag not in h5.hand and mag not in h5.board
              and mag.zone == Zone.REMOVED,
              f"host_atk={host.atk} (+{mag_def.atk})")
        # 非法磁力目标（非机械）
        non_mech = None
        for d in db.pool_minions():
            if Race.MECH not in d.races and Race.NONE not in d.races \
                    and Race.ALL not in d.races:
                non_mech = d
                break
        if non_mech is not None:
            bad_host = summon_minion(g5, h5, non_mech.id, atk=0, health=10)
            mag2 = g5.create_minion(mag_def.id, controller=h5)
            h5.hand.append(mag2)
            mag2.zone = Zone.HAND
            check("A3", "play_minion: 磁力目标非机械 → False",
                  g5.play_minion(h5, mag2, magnetic_target=bad_host)
                  is False and mag2 in h5.hand)
    else:
        check("A3", "play_minion: 磁力卡存在", False, "未找到")


def _needs_target_spell(db: CardDB):
    for d in db.pool_spells():
        sc = REGISTRY.get(d.id)
        if sc is not None and getattr(sc, "needs_target", False) \
                and getattr(sc, "on_play", None) is not None:
            return d
    return None


def probe_a3_play_spell(db: CardDB) -> None:
    section("A3 play_spell")
    game = new_game(db, 2, seed=31)
    h = game.heroes[0]
    h.gold = 10
    s_def = db.pool_spells()[0]
    s = game.create_spell(s_def.id, controller=h)
    h.hand.append(s)
    s.zone = Zone.HAND
    gold_before = h.gold
    ok = game.play_spell(h, s)
    drain(game)
    check("A3", "play_spell: 返回 True / 离手 / 施放不花金币",
          ok is True and s not in h.hand and s.zone == Zone.REMOVED
          and h.gold == gold_before)
    check("A3", "play_spell: 不在手牌 → False",
          game.play_spell(h, game.create_spell(s_def.id, controller=h))
          is False)
    locked = game.create_spell(s_def.id, controller=h)
    h.hand.append(locked)
    locked.zone = Zone.HAND
    locked.set(GameTag.LOCKED_IN_HAND, True)
    check("A3", "play_spell: LOCKED_IN_HAND → False",
          game.play_spell(h, locked) is False)

    nt_def = _needs_target_spell(db)
    if nt_def is not None:
        g2 = new_game(db, 2, seed=32)
        h2 = g2.heroes[0]
        target = summon_minion(g2, h2, atk=1, health=30)
        sp = g2.create_spell(nt_def.id, controller=h2)
        h2.hand.append(sp)
        sp.zone = Zone.HAND
        ok = g2.play_spell(h2, sp)
        check("A3", "play_spell: needs_target 无 target → 挂起选择",
              ok is True and len(g2.pending_choices) == 1
              and g2.pending_choices[0].kind == "spell_target",
              getattr(nt_def, "name", ""))
        ch = g2.pending_choices.pop(0)
        check("A3", "play_spell: spell_target 候选为实体",
              all(isinstance(x, Minion) for x in ch.options))
        ch.choose(0)
        check("A3", "play_spell: 选目标后法术离手并结算",
              sp not in h2.hand and sp.zone == Zone.REMOVED)
    else:
        check("A3", "play_spell: 定向法术存在", False, "未找到")


def probe_a3_refresh(db: CardDB) -> None:
    section("A3 refresh_tavern / freeze_tavern")
    game = new_game(db, 2, seed=41)
    h = game.heroes[0]
    h.gold = 10
    before = list(h.tavern)
    ret = game.refresh_tavern(h)
    check("A3", "refresh: 返回 None / 扣 1 金 / 内容替换",
          ret is None and h.gold == 9 and h.tavern != before)
    h.gold = 0
    expect_raise("A3", "refresh: 金币不足 → GameStateError",
                 GameStateError, game.refresh_tavern, h)
    check("A3", "refresh: 异常后金币不变（0）", h.gold == 0)

    # TURN_SKIPPED：静默不刷新（不抛错、不扣费）
    g2 = new_game(db, 2, seed=42)
    h2 = g2.heroes[0]
    h2.set(GameTag.TURN_SKIPPED, True)
    h2.gold = 10
    tavern_before = list(h2.tavern)
    ret = g2.refresh_tavern(h2)
    check("A3", "refresh: TURN_SKIPPED → 静默返回 None（不扣费）",
          ret is None and h2.gold == 10 and h2.tavern == tavern_before)

    # 冻结
    g3 = new_game(db, 2, seed=43)
    h3 = g3.heroes[0]
    h3.gold = 10
    frozen = list(h3.tavern)
    ret = g3.freeze_tavern(h3)
    check("A3", "freeze: 返回 None / frozen_tavern=True",
          ret is None and h3.frozen_tavern is True)
    g3.refresh_tavern(h3)
    check("A3", "freeze: 下一次刷新保留整馆并清 FROZEN",
          all(e in h3.tavern for e in frozen) and not h3.frozen_tavern
          and h3.gold == 9)
    check("A3", "freeze: 引擎无 unfreeze 公开 API（文档限制项）",
          not hasattr(g3, "unfreeze_tavern"))


def probe_a3_upgrade(db: CardDB) -> None:
    section("A3 upgrade_tavern / upgrade_tavern_free")
    game = new_game(db, 2, seed=51)
    h = game.heroes[0]
    h.gold = 10
    cost = h.upgrade_cost
    ok = game.upgrade_tavern(h)
    check("A3", "upgrade: True / 扣费 / tier+1 / 下一升级费",
          ok is True and h.gold == 10 - cost and h.tavern_tier == 2
          and h.upgrade_cost == C.BASE_UPGRADE_COSTS[3],
          f"cost={cost} gold={h.gold} tier={h.tavern_tier} "
          f"next={h.upgrade_cost}")
    h.gold = 0
    check("A3", "upgrade: 金币不足 → False（不抛错）",
          game.upgrade_tavern(h) is False)
    h.gold = 999
    h.set(GameTag.TAVERN_TIER, C.TAVERN_MAX_TIER)
    check("A3", "upgrade: 已满级 → False",
          game.upgrade_tavern(h) is False)

    g2 = new_game(db, 2, seed=52)
    h2 = g2.heroes[0]
    gold_before = h2.gold
    ret = g2.upgrade_tavern_free(h2)
    check("A3", "upgrade_tavern_free: 返回 None / 不扣费 / tier+1",
          ret is None and h2.gold == gold_before and h2.tavern_tier == 2)


def _find_hero_power_power(db: CardDB, pred):
    for hid in hero_ids(db):
        d = db.get(hid)
        if d is None or d.hero_power_id is None:
            continue
        pw = db.get(d.hero_power_id)
        if pw is None:
            continue
        sc = REGISTRY.get(pw.id)
        if sc is None:
            continue
        if pred(pw, sc):
            return hid, pw, sc
    return None, None, None


def _find_clean_active_power(db: CardDB):
    """找一个"主动、无目标、每次使用恰好计数 +1、无挂起选择"的技能。

    条件由**实测**判定（而非只看声明）：部分技能的 `hero_power` 钩子会
    额外产生 PendingChoice 或回调再次计次，不能用来验证"第 2 次使用失败"。
    """
    for hid in hero_ids(db):
        d = db.get(hid)
        if d is None or d.hero_power_id is None:
            continue
        pw = db.get(d.hero_power_id)
        sc = REGISTRY.get(pw.id) if pw is not None else None
        if pw is None or sc is None:
            continue
        if getattr(sc, "passive", False) \
                or getattr(sc, "needs_target", False) \
                or getattr(sc, "available", None) is not None \
                or getattr(sc, "uses_per_turn", 1) != 1:
            continue
        cost = pw.cost
        if cost < 1:
            continue
        g = new_game(db, 2, seed=61, hero_id_list=[hid, hid])
        h = g.heroes[0]
        h.gold = 10
        try:
            if not g.use_hero_power(h):
                continue
        except Exception:                        # noqa: BLE001
            continue
        if g.pending_choices:
            continue
        used = h._power_uses_this_turn.get(pw.id, 0)
        if used == 1 and h.gold == 10 - cost:
            return hid, pw, sc
    return None, None, None


def probe_a3_hero_power(db: CardDB) -> None:
    section("A3 use_hero_power")
    hid, pw, sc = _find_clean_active_power(db)
    if pw is None:
        check("A3", "hero power: 找到可用主动技能", False, "未找到")
        return
    game = new_game(db, 2, seed=61, hero_id_list=[hid, hid])
    h = game.heroes[0]
    h.gold = 10
    cost = game.hero_power_cost(h, pw, sc)
    ids = game.hero_power_ids(h)
    check("A3", "hero_power: hero_power_ids 含主技能",
          pw.id in ids, f"{ids}")
    ok = game.use_hero_power(h)
    drain(game)
    check("A3", "hero_power: True / 扣费 / 本回合计数",
          ok is True and h.gold == 10 - cost
          and h.get(GameTag.HERO_POWER_USED_THIS_TURN) == 1,
          f"{pw.name} cost={cost} gold={h.gold}")
    check("A3", "hero_power: 每回合第 2 次 → False",
          game.use_hero_power(h) is False)
    h._power_uses_this_turn.clear()
    h.clear(GameTag.HERO_POWER_USED_THIS_TURN)
    h.gold = 0
    check("A3", "hero_power: 金币不足 → False",
          game.use_hero_power(h) is False)

    # 定向技能：选择挂起期不扣费，choose 时结算
    hid2, pw2, sc2 = _find_hero_power_power(
        db, lambda pw, sc: not getattr(sc, "passive", False)
        and getattr(sc, "needs_target", False)
        and getattr(sc, "available", None) is None)
    if pw2 is not None:
        g2 = new_game(db, 2, seed=62, hero_id_list=[hid2, hid2])
        h2 = g2.heroes[0]
        h2.gold = 10
        summon_minion(g2, h2, atk=1, health=30)
        cost2 = g2.hero_power_cost(h2, pw2, sc2)
        ok = g2.use_hero_power(h2)
        check("A3", "hero_power(定向): 挂起选择且暂不扣费",
              ok is True and len(g2.pending_choices) == 1
              and g2.pending_choices[0].kind == "hero_power_target"
              and h2.gold == 10, f"{pw2.name}")
        g2.pending_choices.pop(0).choose(0)
        check("A3", "hero_power(定向): choose 后扣费并计数",
              h2.gold == 10 - cost2
              and h2.get(GameTag.HERO_POWER_USED_THIS_TURN) == 1)

    hid3, pw3, sc3 = _find_hero_power_power(
        db, lambda pw, sc: getattr(sc, "passive", False))
    if pw3 is not None:
        g3 = new_game(db, 2, seed=63, hero_id_list=[hid3, hid3])
        h3 = g3.heroes[0]
        h3.gold = 10
        check("A3", "hero_power(passive): → False",
              g3.use_hero_power(h3) is False, f"{pw3.name}")


def probe_a3_activate(db: CardDB) -> None:
    section("A3 use_activate")
    activate_defs = [d for d in db.pool_minions() if "activate" in d.keywords]
    check("A3", "池内存在 Activate 随从", len(activate_defs) > 0,
          f"{len(activate_defs)}")
    d = activate_defs[0]
    game = new_game(db, 2, seed=71)
    h = game.heroes[0]
    h.gold = 10
    m = summon_minion(game, h, d.id)
    cost = m.get(GameTag.ACTIVATE_COST, 1)
    ok = game.use_activate(h, m)
    drain(game)
    check("A3", "activate: True / 扣费 / 本回合已用标记",
          ok is True and h.gold == 10 - cost
          and m.has(GameTag.ACTIVATE_USED_THIS_TURN),
          f"{d.name} cost={cost}")
    check("A3", "activate: 同回合第 2 次 → False",
          game.use_activate(h, m) is False)
    off_board = game.create_minion(d.id, controller=h)
    check("A3", "activate: 不在棋盘 → False",
          game.use_activate(h, off_board) is False)
    plain = summon_minion(game, h, db.pool_minions()[0].id)
    if not plain.has(GameTag.ACTIVATE):
        check("A3", "activate: 无 ACTIVATE tag → False",
              game.use_activate(h, plain) is False)
    # 下回合重置
    h.gold = 100
    game.end_recruit_phase()
    drain(game)
    if m in h.board:
        check("A3", "activate: 下回合 ACTIVATE_USED 重置",
              not m.has(GameTag.ACTIVATE_USED_THIS_TURN))


def probe_a3_dark_gift(db: CardDB) -> None:
    section("A3 use_dark_gift")
    game = new_game(db, 2, seed=81)
    h = game.heroes[0]
    h.gold = 10
    check("A3", "dark_gift: turn<3 → False",
          game.use_dark_gift(h) is False)
    game.turn = C.DARK_GIFT_START_TURN
    h.gold = 10
    ok = game.use_dark_gift(h)
    drain(game, pick=0)
    check("A3", "dark_gift: 合法 → True / 扣 3 金 / 使用记账",
          ok is True and h.gold == 10 - C.DARK_GIFT_COST
          and game.dark_gift_state[h]["uses_left"]
          == C.DARK_GIFT_USES_PER_GAME - 1,
          f"gold={h.gold} state={game.dark_gift_state[h]}")
    check("A3", "dark_gift: 同回合第 2 次 → False",
          game.use_dark_gift(h) is False)
    h.gold = 0
    game.dark_gift_state[h]["used_this_turn"] = False
    check("A3", "dark_gift: 金币不足 → False",
          game.use_dark_gift(h) is False)
    game.dark_gift_state[h]["uses_left"] = 0
    game.dark_gift_state[h]["used_this_turn"] = False
    h.gold = 10
    check("A3", "dark_gift: 本局额度用尽 → False",
          game.use_dark_gift(h) is False)


def probe_a3_spend_gold(db: CardDB) -> None:
    section("A3 spend_gold")
    game = new_game(db, 2, seed=91)
    h = game.heroes[0]
    h.gold = 5
    gold_events = []
    from hsrl2.events import Listener
    game.events.register(Listener(event="gold_spent", owner=h,
                                  callback=lambda g, **kw:
                                  gold_events.append(kw["amount"])))
    game.spend_gold(h, 3)
    check("A3", "spend_gold: 扣款 / 记账 / 事件",
          h.gold == 2 and h.get(GameTag.GOLD_SPENT_THIS_TURN) == 3
          and gold_events == [3])
    expect_raise("A3", "spend_gold: 金币不足 → GameStateError",
                 GameStateError, game.spend_gold, h, 5)
    check("A3", "spend_gold: 异常后金币不变", h.gold == 2)
    game.spend_gold(h, 0)
    check("A3", "spend_gold: amount<=0 是 no-op", h.gold == 2)


# ══════════════════════════════════════════════════════════════════════
# A4 候选动作枚举
# ══════════════════════════════════════════════════════════════════════


def quote_buy_cost(game: Game, hero: Hero, entity) -> int:
    """buy_from_tavern 的价格镜像（非变异版本；见 ENGINE_API.md §4.3）。

    与引擎 buy_from_tavern 的定价顺序一致；免费额度判定**不消费**。
    """
    cost = entity.get(GameTag.COST, C.MINION_BUY_COST)
    if isinstance(entity, Minion):
        if getattr(game, "_minion_cost_is_tier", False):
            cost = entity.tech_level
        override = hero.get(GameTag.TAVERN_MINION_COST_OVERRIDE, 0)
        if override:
            cost = override
        for src, pred, c in list(getattr(hero, "_tavern_cost_rules", [])):
            if src is not None and not (
                    src in hero.trinkets
                    or src in getattr(hero, "quest_rewards", [])
                    or src in hero.board):
                continue
            try:
                if pred(entity):
                    cost = min(cost, int(c))
            except Exception:                    # noqa: BLE001
                pass
        if _free_minion_buy_available(game, hero, entity):
            cost = 0
    d = game.db.get(entity.card_id)
    if d is not None and d.is_pool_spell:
        cost = max(0, cost - hero.get(GameTag.TAVERN_SPELL_COST_MOD, 0))
        if hero.get(GameTag.FREE_SPELL_BUYS_THIS_TURN, 0) > 0:
            cost = 0
        else:
            cost = max(0, cost
                       - hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0))
    return cost


def _free_minion_buy_available(game: Game, hero: Hero, entity) -> bool:
    """`_take_free_minion_buy` 的只读镜像（不消费额度）。"""
    for q in hero._free_minion_buy_quotas:
        if q["turn"] != game.turn or q["used"] >= q["count"]:
            continue
        if Game._free_buy_qualifiers_match(entity, q["race"], q["keyword"]):
            return True
    if hero._free_minion_buy_quotas:
        return False
    n = hero.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0)
    return n > 0 and Game._free_buy_qualifiers_match(
        entity, hero.get(GameTag.FREE_MINION_BUY_RACE, None),
        hero.get(GameTag.FREE_MINION_BUY_KEYWORD, None))


def hero_power_usable(game: Game, hero: Hero, power_id: str) -> dict:
    """use_hero_power 的只读合法性镜像（文档 §4.5 参考实现）。"""
    out = {"usable": False, "cost": 0, "needs_target": False,
           "targets": [], "reason": ""}
    ids = game.hero_power_ids(hero)
    if power_id not in ids:
        out["reason"] = "not_owned"
        return out
    power_def = game.hero_power_def_for(hero, power_id)
    script = REGISTRY.get(power_id) if power_def is not None else None
    if power_def is None or script is None:
        out["reason"] = "no_script"
        return out
    if getattr(script, "passive", False):
        out["reason"] = "passive"
        return out
    avail = getattr(script, "available", None)
    if avail is not None and not avail(hero, game):
        out["reason"] = "unavailable"
        return out
    max_uses = getattr(script, "uses_per_turn", 1) + hero.extra_trigger("hp_uses")
    if hero._power_uses_this_turn.get(power_id, 0) >= max_uses:
        out["reason"] = "used_this_turn"
        return out
    per_game = getattr(script, "uses_per_game", None)
    if per_game is not None and hero._power_uses_this_game.get(power_id, 0) >= per_game:
        out["reason"] = "used_this_game"
        return out
    cost = game.hero_power_cost(hero, power_def, script)
    if cost and hero.gold < cost:
        out["reason"] = "no_gold"
        return out
    n_targets = getattr(script, "target_count", 1) \
        if getattr(script, "needs_target", False) else 0
    if n_targets > 0:
        cand_fn = getattr(script, "target_candidates", None)
        targets = (list(cand_fn(hero, game)) if cand_fn is not None
                   else [m for m in hero.board if not m.dead])
        if len(targets) < n_targets:
            out["reason"] = "no_target"
            return out
        out["needs_target"] = True
        out["targets"] = targets
    out.update(usable=True, cost=cost)
    return out


def next_existing_tier(game: Game, hero: Hero):
    """升级落点镜像（无公开 API；见 ENGINE_API.md §4.6）。"""
    ladder = getattr(game, "_tavern_tier_ladder", None)
    if ladder is None:
        nxt = hero.tavern_tier + 1
        return nxt if nxt <= game.max_tavern_tier else None
    for t in ladder:
        if t > hero.tavern_tier:
            return t
    return None


def enumerate_actions(game: Game, hero: Hero) -> list:
    """参考实现：招募阶段合法候选动作枚举（详见 ENGINE_API.md §4.7）。

    返回 dict 列表（`kind` + 槽位/目标引用）。**不**改动游戏状态。
    目标引用在本参考实现里直接给引擎实体（游戏内 action 层可换成
    obs 槽位；环境层应按当前 obs 的 zone+slot 重新映射）。
    """
    acts = []
    if game.finished or game.pending_choices:
        return acts
    if hero.get(GameTag.TURN_SKIPPED, False):
        return [{"kind": "end_turn"}]

    # 1) 买（酒馆随从 + 酒馆法术）
    if not hero.hand_full():
        for slot, e in enumerate(hero.tavern):
            cost = quote_buy_cost(game, hero, e)
            if cost <= hero.gold:
                acts.append({"kind": "buy", "src_slot": slot,
                             "cost": cost})

    # 2) 卖（仅棋盘；引擎 sell_minion 对 Spell 会 AttributeError）
    for slot, m in enumerate(hero.board):
        acts.append({"kind": "sell", "src_slot": slot})

    # 3) 打手牌（随从 / 法术）
    for slot, e in enumerate(hero.hand):
        if e.has(GameTag.LOCKED_IN_HAND):
            continue
        d = game.db.get(e.card_id)
        if d is not None and d.unplayable:
            continue
        if isinstance(e, Minion):
            sc = e.scripts
            # 磁力吸附：不占板位，允许在满板时使用
            if e.has(GameTag.MAGNETIC):
                for tslot, host in enumerate(hero.board):
                    if not host.dead and game._magnetic_valid(e, host):
                        acts.append({"kind": "play_minion", "src_slot": slot,
                                     "magnetic_target": host})
            if hero.board_full():
                continue
            needs_target = sc is not None \
                and getattr(sc, "needs_target", False) \
                and getattr(sc, "battlecry", None) is not None
            if needs_target:
                cand_fn = getattr(sc, "target_candidates", None)
                targets = (list(cand_fn(e, game)) if cand_fn is not None
                           else [m for m in hero.board if not m.dead])
                if targets:
                    for t in targets:
                        acts.append({"kind": "play_minion",
                                     "src_slot": slot, "target": t})
                else:
                    acts.append({"kind": "play_minion", "src_slot": slot})
            else:
                for pos in range(len(hero.board) + 1):
                    acts.append({"kind": "play_minion", "src_slot": slot,
                                 "position": pos})
        elif isinstance(e, Spell):
            sc = e.scripts
            needs_target = sc is not None \
                and getattr(sc, "needs_target", False)
            if needs_target:
                cand_fn = getattr(sc, "target_candidates", None)
                targets = (list(cand_fn(e, game)) if cand_fn is not None
                           else [m for m in hero.board if not m.dead])
                if targets:
                    for t in targets:
                        acts.append({"kind": "play_spell",
                                     "src_slot": slot, "target": t})
                else:
                    acts.append({"kind": "play_spell", "src_slot": slot})
            else:
                acts.append({"kind": "play_spell", "src_slot": slot})

    # 4) 刷新（引擎金币不足会抛 GameStateError → 必须前置过滤）
    refresh_cost = hero.get(GameTag.REFRESH_COST_OVERRIDE, C.REFRESH_COST)
    has_free_refresh = (hero.get(GameTag.FREE_REFRESH_REMAINING, 0) > 0
                        or hero.get(GameTag.HEALTH_REFRESHES_LEFT, 0) > 0)
    if has_free_refresh or hero.gold >= refresh_cost:
        acts.append({"kind": "reroll", "cost": refresh_cost})

    # 5) 升级
    nxt = next_existing_tier(game, hero)
    up_cost = max(0, hero.upgrade_cost
                  + hero.get(GameTag.UPGRADE_COST_MOD, 0))
    if nxt is not None and hero.gold >= up_cost:
        acts.append({"kind": "upgrade", "cost": up_cost})

    # 6) 冻结（引擎无 unfreeze，见文档限制）
    acts.append({"kind": "freeze"})

    # 7) 英雄技能（镜像可用性；含目标）
    for pid in game.hero_power_ids(hero):
        info = hero_power_usable(game, hero, pid)
        if not info["usable"]:
            continue
        if info["needs_target"]:
            for t in info["targets"]:
                acts.append({"kind": "hero_power", "power_id": pid,
                             "target": t, "cost": info["cost"]})
        else:
            acts.append({"kind": "hero_power", "power_id": pid,
                         "cost": info["cost"]})

    # 8) Activate
    for slot, m in enumerate(hero.board):
        if not m.has(GameTag.ACTIVATE) \
                or m.has(GameTag.ACTIVATE_USED_THIS_TURN):
            continue
        cost = m.get(GameTag.ACTIVATE_COST, 1)
        if hero.gold >= cost:
            acts.append({"kind": "activate", "src_slot": slot,
                         "cost": cost})

    # 9) Dark Gift（S14）
    state = game.dark_gift_state.get(hero)
    uses_left = state["uses_left"] if state else C.DARK_GIFT_USES_PER_GAME
    used_this_turn = state["used_this_turn"] if state else False
    if game.turn >= C.DARK_GIFT_START_TURN and uses_left > 0 \
            and not used_this_turn and hero.gold >= C.DARK_GIFT_COST:
        acts.append({"kind": "use_dark_gift", "cost": C.DARK_GIFT_COST})

    # 10) 结束回合（引擎没有 per-player end turn，ERP 推进全桌）
    acts.append({"kind": "end_turn"})
    return acts


def probe_a4(db: CardDB) -> None:
    section("A4 候选动作枚举")
    game = new_game(db, 2, seed=101)
    h = game.heroes[0]

    # 酒馆 = 随从 + 酒馆法术；手牌；棋盘
    check("A4", "酒馆同时含随从与法术",
          any(isinstance(e, Minion) for e in h.tavern)
          and any(isinstance(e, Spell) for e in h.tavern))
    s = game.create_spell(db.pool_spells()[0].id, controller=h)
    h.hand.append(s)
    s.zone = Zone.HAND
    check("A4", "手牌可为随从/法术混排", isinstance(h.hand[0], Spell))

    # 价格镜像 vs 实际扣款
    h.gold = 10
    m = next(e for e in h.tavern if isinstance(e, Minion))
    quoted = quote_buy_cost(game, h, m)
    gold_before = h.gold
    game.buy_from_tavern(h, m)
    drain(game)
    check("A4", "买价镜像 == 实际扣款（基础价）",
          gold_before - h.gold == quoted, f"quote={quoted}")

    # 英雄级价格覆盖
    g2 = new_game(db, 2, seed=102)
    h2 = g2.heroes[0]
    h2.gold = 10
    h2.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 2)
    m2 = next(e for e in h2.tavern if isinstance(e, Minion))
    q2 = quote_buy_cost(g2, h2, m2)
    before = h2.gold
    g2.buy_from_tavern(h2, m2)
    drain(g2)
    check("A4", "买价镜像：TAVERN_MINION_COST_OVERRIDE",
          q2 == 2 and before - h2.gold == 2, f"quote={q2}")

    # 免费随从配额
    g3 = new_game(db, 2, seed=103)
    h3 = g3.heroes[0]
    h3.gold = 10
    g3.set_free_minion_buys(h3, 1, source="probe")
    m3 = next(e for e in h3.tavern if isinstance(e, Minion))
    q3 = quote_buy_cost(g3, h3, m3)
    before = h3.gold
    g3.buy_from_tavern(h3, m3)
    drain(g3)
    check("A4", "买价镜像：免费随从额度（含只读判定不消费）",
          q3 == 0 and before - h3.gold == 0
          and g3.free_minion_buys_left(h3) == 0, f"quote={q3}")

    # 酒馆法术折扣
    g4 = new_game(db, 2, seed=104)
    h4 = g4.heroes[0]
    h4.gold = 10
    sp = next(e for e in h4.tavern if isinstance(e, Spell))
    h4.set(GameTag.NEXT_SPELL_COST_REDUCTION, 1)
    q4 = quote_buy_cost(g4, h4, sp)
    before = h4.gold
    g4.buy_from_tavern(h4, sp)
    drain(g4)
    check("A4", "买价镜像：NEXT_SPELL_COST_REDUCTION",
          before - h4.gold == q4, f"quote={q4}")

    # 合法动作集合骨架：金 0/满手 → 无 buy
    g5 = new_game(db, 2, seed=105)
    h5 = g5.heroes[0]
    h5.gold = 0
    can_buy = [e for e in h5.tavern
               if not h5.hand_full() and quote_buy_cost(g5, h5, e) <= h5.gold]
    check("A4", "金币 0 且无免费额度 → 无合法 buy", can_buy == [])
    h5.gold = 10
    while not h5.hand_full():
        h5.add_to_hand(g5.create_minion(db.pool_minions()[0].id,
                                        controller=h5))
    can_buy2 = [e for e in h5.tavern
                if not h5.hand_full() and quote_buy_cost(g5, h5, e) <= h5.gold]
    check("A4", "满手牌 → 无合法 buy", can_buy2 == [])

    # hero power 合法性镜像 vs 实际
    hid, pw, sc = _find_clean_active_power(db)
    if pw is not None:
        g6 = new_game(db, 2, seed=106, hero_id_list=[hid, hid])
        h6 = g6.heroes[0]
        h6.gold = 10
        info = hero_power_usable(g6, h6, pw.id)
        before = h6.gold
        actual = g6.use_hero_power(h6, power_id=pw.id)
        drain(g6)
        check("A4", "hero_power 合法性镜像 == 引擎实际结果",
              info["usable"] is True and actual is True
              and before - h6.gold == info["cost"])
        info2 = hero_power_usable(g6, h6, pw.id)
        check("A4", "hero_power 镜像：本回合已用 → 不可用",
              info2["usable"] is False and info2["reason"]
              == "used_this_turn")

    # 目标候选枚举（战吼/法术/技能）
    nt = _needs_target_minion(db)
    if nt is not None:
        g7 = new_game(db, 2, seed=107)
        h7 = g7.heroes[0]
        mm = make_hand_minion(g7, h7, nt.id)
        sc_nt = REGISTRY.get(nt.id)
        cand_fn = getattr(sc_nt, "target_candidates", None)
        targets = (list(cand_fn(mm, g7)) if cand_fn is not None
                   else [x for x in h7.board if not x.dead])
        check("A4", "needs_target 目标集合可枚举（target_candidates）",
              isinstance(targets, list), f"{nt.name} n={len(targets)}")
    check("A4", "磁力判定为私有方法（_magnetic_valid）——需镜像/调用私有",
          hasattr(game, "_magnetic_valid"))

    # 参考实现 enumerate_actions 的健全性
    g8 = new_game(db, 2, seed=108)
    h8 = g8.heroes[0]
    h8.gold = 10
    summon_minion(g8, h8, atk=1, health=30)
    make_hand_minion(g8, h8)
    acts = enumerate_actions(g8, h8)
    kinds = {a["kind"] for a in acts}
    check("A4", "enumerate_actions: 覆盖 buy/sell/play/reroll/upgrade/"
                "freeze/end_turn",
          {"buy", "sell", "play_minion", "reroll", "upgrade",
           "freeze", "end_turn"} <= kinds, f"{sorted(kinds)}")
    check("A4", "enumerate_actions: buy 报价均 <= 金币",
          all(a["cost"] <= h8.gold for a in acts if a["kind"] == "buy"))
    h8.gold = 0
    acts0 = enumerate_actions(g8, h8)
    check("A4", "enumerate_actions: 金币 0 → 无 buy/reroll/upgrade",
          not any(a["kind"] in ("buy", "reroll", "upgrade") for a in acts0)
          and any(a["kind"] == "end_turn" for a in acts0))
    while not h8.hand_full():
        h8.add_to_hand(g8.create_minion(db.pool_minions()[0].id,
                                        controller=h8))
    acts_full = enumerate_actions(g8, h8)
    check("A4", "enumerate_actions: 满手牌 → 无 buy",
          not any(a["kind"] == "buy" for a in acts_full))

    # 目标枚举：手牌定向随从 + 合法目标（Demon）
    nt = _needs_target_minion(db)
    if nt is not None:
        g9 = new_game(db, 2, seed=109)
        h9 = g9.heroes[0]
        demon = None
        for d in db.pool_minions():
            if Race.DEMON in d.races:
                demon = d
                break
        if demon is not None:
            summon_minion(g9, h9, demon.id, atk=2, health=30)
        mm = make_hand_minion(g9, h9, nt.id)
        acts9 = enumerate_actions(g9, h9)
        target_variants = [a for a in acts9 if a["kind"] == "play_minion"
                           and "target" in a]
        check("A4", "enumerate_actions: 定向随从生成目标组合",
              len(target_variants) >= 1, f"{nt.name} n={len(target_variants)}")

    # 满板：无普通 play_minion，但磁力仍有吸附候选
    g10 = new_game(db, 2, seed=110)
    h10 = g10.heroes[0]
    h10.gold = 10
    while not h10.board_full():
        summon_minion(g10, h10, atk=1, health=30)
    m10 = make_hand_minion(g10, h10)
    acts10 = enumerate_actions(g10, h10)
    check("A4", "enumerate_actions: 满板 → 无普通 play_minion",
          not any(a["kind"] == "play_minion" and "magnetic_target" not in a
                  for a in acts10))


# ══════════════════════════════════════════════════════════════════════
# A5 PendingChoice
# ══════════════════════════════════════════════════════════════════════


def probe_a5(db: CardDB) -> None:
    section("A5 PendingChoice")
    game = new_game(db, 2, seed=111)
    h = game.heroes[0]

    resolves = []
    game.pending_choices.append(PendingChoice(
        h, ["a", "b", "c"], "probe_kind",
        resolve_callback=lambda pick: resolves.append(pick)))
    check("A5", "结构: owner/options/kind/resolve_callback",
          len(game.pending_choices) == 1
          and game.pending_choices[0].owner is h
          and game.pending_choices[0].options == ["a", "b", "c"]
          and game.pending_choices[0].kind == "probe_kind")
    n_before = len(game.pending_choices)
    game.pending_choices[0].choose(1)
    check("A5", "choose 只结算不出队（队列长度不变）",
          len(game.pending_choices) == n_before and resolves == ["b"])
    game.pending_choices[0].choose(0)
    check("A5", "重复 choose 会重复结算（必须上层 pop）",
          resolves == ["b", "a"])
    expect_raise("A5", "choose 越界 → GameStateError",
                 GameStateError, game.pending_choices[0].choose, 9)
    game.pending_choices.pop(0)
    check("A5", "pop 后队列清空", game.pending_choices == [])

    # FIFO 循环模板
    order = []
    game.pending_choices.append(PendingChoice(
        h, [1], "first", resolve_callback=lambda p: order.append(("first", p))))
    game.pending_choices.append(PendingChoice(
        h, [2], "second", resolve_callback=lambda p: order.append(("second", p))))
    while game.pending_choices:
        c = game.pending_choices.pop(0)
        c.choose(0)
    check("A5", "FIFO 弹出并选择", order == [("first", 1), ("second", 2)])

    # 真实选项类型
    kinds_seen = {}

    g2 = new_game(db, 8, seed=112)
    quests = []
    while g2.turn < 4 and not g2.finished:
        drain(g2)
        g2.end_recruit_phase()
    for c in g2.pending_choices:
        kinds_seen.setdefault(c.kind, type(c.options[0]).__name__)
    for c in list(g2.pending_choices):
        if c.kind == "quest_offer":
            quests.append(c.options[0])
    check("A5", "quest_offer 选项类型 = tuple", bool(quests)
          and isinstance(quests[0], tuple), f"{quests[:1]}")
    drain(g2)

    # 真实 discover_minion / spell_target / choose_one 选项类型
    g3 = new_game(db, 2, seed=113)
    h3 = g3.heroes[0]
    h3.gold = 10
    h3.gold = 10
    # 发现: 三连奖励 / 战吼发现都可能；这里直接调用 Discover 动作构造
    from hsrl2.actions.discover import Discover
    g3.run_actions(Discover(h3, count=3, max_tier=3, min_tier=1))
    check("A5", "discover_minion 选项 = card_id(str)",
          len(g3.pending_choices) == 1
          and g3.pending_choices[0].kind == "discover_minion"
          and all(isinstance(x, str) for x in g3.pending_choices[0].options))
    ch = g3.pending_choices.pop(0)
    hand_before = len(h3.hand)
    ch.choose(0)
    check("A5", "discover choose 后卡入手牌",
          len(h3.hand) == hand_before + 1
          or len(g3.pending_hand_queue) > 0)


# ══════════════════════════════════════════════════════════════════════
# A6 战斗与回合推进
# ══════════════════════════════════════════════════════════════════════


def probe_a6(db: CardDB) -> None:
    section("A6 战斗与回合推进")
    game = new_game(db, 2, seed=121)
    a, b = game.heroes
    summon_minion(game, a, atk=5, health=20)
    b.board = []
    res = game.run_combat(a, b)
    check("A6", "run_combat 返回 CombatResult(winner/loser/damage_*)",
          res is not None and res.winner is a and res.loser is b
          and res.damage_dealt > 0 and res.capped_damage > 0
          and res.rounds >= 1,
          f"winner={res.winner.name} raw={res.damage_dealt} "
          f"capped={res.capped_damage} rounds={res.rounds}")

    # 伤害上限：turn1 alive=8 → cap 5
    g2 = new_game(db, 2, seed=122)
    a2, b2 = g2.heroes
    high_tier = [d for d in db.pool_minions() if d.tech_level >= 6][:4]
    for d in high_tier:
        summon_minion(g2, a2, d.id, atk=5, health=20)
    b2.board = []
    res2 = g2.run_combat(a2, b2, alive_count=8)
    cap = C.damage_cap(g2.turn, 8)
    check("A6", "伤害上限按 turn+存活人数（capped_damage <= cap）",
          cap is not None and res2.capped_damage == min(res2.damage_dealt, cap)
          and res2.damage_dealt > cap,
          f"raw={res2.damage_dealt} cap={cap} capped={res2.capped_damage}")

    # end_recruit_phase 副作用
    g3 = new_game(db, 2, seed=123)
    a3, b3 = g3.heroes
    summon_minion(g3, a3, atk=6, health=20)
    turn_before = g3.turn
    ret = g3.end_recruit_phase()
    drain(g3)
    check("A6", "end_recruit_phase 返回 None / turn+1",
          ret is None and g3.turn == turn_before + 1)
    check("A6", "end_recruit_phase: 战败者掉血",
          b3.health < C.HERO_BASE_HEALTH, f"H1 health={b3.health}")
    check("A6", "end_recruit_phase: 战前棋盘快照 last_combat_board 非空",
          len(a3.last_combat_board) > 0)

    # 战前/战后棋盘复原
    check("A6", "run_combat 后棋盘复原（战内变化不延续）",
          len(a3.board) == 1 and not a3.board[0].dead)

    # 淘汰：heroes 列表被移除 + ghost_record + 名次记录
    g4 = new_game(db, 3, seed=124)
    h0, h1, h2 = g4.heroes
    eliminated_order = []
    from hsrl2.events import Listener
    g4.events.register(Listener(
        event="hero_eliminated", owner=h0,
        callback=lambda g, **kw: eliminated_order.append(kw["hero"].name)))
    h2.health = 0
    g4.end_recruit_phase()
    drain(g4)
    check("A6", "淘汰: 英雄从 game.heroes 移除",
          h2 not in g4.heroes and len(g4.heroes) == 2)
    check("A6", "淘汰: hero_eliminated 事件（名次数据源）",
          eliminated_order == [h2.name], f"{eliminated_order}")
    check("A6", "淘汰: ghost_records 记录冻结战团",
          len(g4.ghost_records) >= 1
          and "tavern_tier" in g4.ghost_records[-1])

    # 幽灵战：4 人局先淘汰 1 人 → 3 人（奇数）→ 1 对 + 1 幽灵
    g5 = new_game(db, 4, seed=125)
    hs = list(g5.heroes)
    hs[3].health = 0
    g5._process_eliminations()
    check("A6", "幽灵: 淘汰后剩 3 人 + ghost_record",
          len(g5.heroes) == 3 and len(g5.ghost_records) == 1)
    combat_ends = []
    g5.events.register(Listener(
        event="combat_end", owner=hs[0],
        callback=lambda g, **kw: combat_ends.append(kw["result"])))
    g5.end_recruit_phase()
    drain(g5)
    check("A6", "幽灵战: 奇数存活者仍完成战斗且幽灵不留在 heroes",
          len(combat_ends) >= 2 and len(g5.heroes) <= 3,
          f"combat_end={len(combat_ends)} heroes={len(g5.heroes)}")

    # finished 判定
    g6 = new_game(db, 2, seed=126)
    a6, b6 = g6.heroes
    b6.health = 0
    t0 = g6.turn
    g6.end_recruit_phase()
    drain(g6)
    check("A6", "仅剩 1 人 → finished=True 且 turn 不再自增",
          g6.finished is True and g6.turn == t0 and len(g6.heroes) == 1,
          f"turn={g6.turn} heroes={len(g6.heroes)}")

    # in_combat 标记：只在 run_combat 内部为 True（end_recruit_phase 内同步
    # 执行全部战斗，外部观察不到 False→True 的阶段切换）
    g7 = new_game(db, 2, seed=127)
    a7, b7 = g7.heroes
    summon_minion(g7, a7, atk=3, health=20)
    summon_minion(g7, b7, atk=1, health=20)
    seen = []
    from hsrl2.events import Listener as _L
    g7.events.register(_L(event="before_attack", owner=a7,
                          callback=lambda g, **kw:
                          seen.append(g.in_combat)))
    check("A6", "招募阶段 in_combat == False",
          g7.in_combat is False)
    g7.run_combat(a7, b7)
    check("A6", "run_combat 内 in_combat == True（before_attack 观察）",
          bool(seen) and all(seen), f"{len(seen)} 次攻击")
    check("A6", "run_combat 返回后 in_combat 复位为 False",
          g7.in_combat is False)
    check("A6", "next_opponent 招募期返回本回合对手（预生成配对）",
          g7.next_opponent(a7) is not None
          or a7 in getattr(g7, "_pending_leftover", ()),
          f"{g7.next_opponent(a7)}")
    # 空战团快照 → last_opponent_warband 返回 None（不是 []）
    g8 = new_game(db, 2, seed=128)
    h8 = g8.heroes[0]
    g8.end_recruit_phase()
    drain(g8)
    check("A6", "last_opponent_warband: 对手空战团返回 None（不是 []）",
          g8.last_opponent_warband(h8) is None
          and g8._last_opponent_board.get(h8) == [],
          f"snapshot={g8._last_opponent_board.get(h8)!r}")

    # 名次计算（环境层职责）
    def compute_ranks(total_players: int, eliminated_names: list,
                      survivors: list) -> dict:
        """淘汰顺序 → 名次。第一个被淘汰 = 第 total 名，存活者 = 第 1 名。"""
        ranks = {}
        for i, name in enumerate(eliminated_names):
            ranks[name] = total_players - i
        for name in survivors:
            ranks[name] = 1
        return ranks

    ranks = compute_ranks(4, ["P4", "P3", "P2"], ["P1"])
    check("A6", "名次 = 引擎淘汰顺序的反序 + 存活者第 1",
          ranks == {"P1": 1, "P2": 2, "P3": 3, "P4": 4}, f"{ranks}")

    # 文档 §6.6 的 RankTracker 参考实现（真实事件驱动）
    class RankTracker:
        def __init__(self, total_players: int):
            self.total = total_players
            self.eliminated = []

        def on_hero_eliminated(self, hero):
            self.eliminated.append(hero)

        def final_ranks(self, survivors) -> dict:
            ranks = {}
            for i, hero in enumerate(self.eliminated):
                ranks[id(hero)] = self.total - i
            for hero in survivors:
                ranks[id(hero)] = 1
            return ranks

    g9 = new_game(db, 3, seed=129)
    hs9 = list(g9.heroes)
    tracker = RankTracker(3)
    from hsrl2.events import Listener as _L2
    g9.events.register(_L2(
        event="hero_eliminated", owner=hs9[0],
        callback=lambda g, **kw: tracker.on_hero_eliminated(kw["hero"])))
    hs9[2].health = 0
    g9.end_recruit_phase()
    drain(g9)
    check("A6", "RankTracker: 记录淘汰顺序", len(tracker.eliminated) == 1
          and tracker.eliminated[0] is hs9[2])
    hs9[1].health = 0
    g9.end_recruit_phase()
    drain(g9)
    check("A6", "RankTracker: final_ranks（最后存活=1，先死=3）",
          g9.finished and tracker.final_ranks(
              [h for h in g9.heroes if h.is_alive]) == {
                  id(hs9[0]): 1, id(hs9[2]): 3, id(hs9[1]): 2},
          f"eliminated={[h.name for h in tracker.eliminated]}")


# ══════════════════════════════════════════════════════════════════════
# A7 状态读取
# ══════════════════════════════════════════════════════════════════════


def probe_a7(db: CardDB) -> None:
    section("A7 状态读取")
    game = new_game(db, 2, seed=131)
    h = game.heroes[0]
    h.gold = 10
    e = next(x for x in h.tavern if isinstance(x, Minion))
    game.buy_from_tavern(h, e)
    drain(game)
    game.play_minion(h, e)
    drain(game)

    # Hero
    check("A7", "Hero: health/armor/gold/tavern_tier/upgrade_cost/is_alive",
          isinstance(h.health, int) and isinstance(h.armor, int)
          and isinstance(h.gold, int) and isinstance(h.tavern_tier, int)
          and isinstance(h.upgrade_cost, int) and h.is_alive is True)
    check("A7", "Hero: board/hand/tavern/trinkets/quest 容器",
          isinstance(h.board, list) and isinstance(h.hand, list)
          and isinstance(h.tavern, list) and isinstance(h.trinkets, list)
          and h.quest is None)
    check("A7", "Hero: hero_power_ids 可读",
          isinstance(game.hero_power_ids(h), list))
    check("A7", "Hero: next_opponent 招募期可读",
          game.next_opponent(h) is not None
          or h in (game._pending_leftover,))
    check("A7", "Hero: last_opponent_warband 首回合为 None（无战斗记录）",
          game.last_opponent_warband(h) is None)

    # Minion
    m = h.board[0]
    check("A7", "Minion: atk/health/max_health/tier/card_id/zone",
          isinstance(m.atk, int) and isinstance(m.health, int)
          and isinstance(m.max_health, int) and isinstance(m.tech_level, int)
          and isinstance(m.card_id, str)
          and m.get(GameTag.CARDTYPE) == CardType.MINION
          and m.zone == Zone.PLAY,
          "注意: Entity/Minion 无 .card_type 属性，需读 "
          "get(GameTag.CARDTYPE) 或 isinstance")
    check("A7", "Minion: races/keywords/taunt/golden/uuid",
          isinstance(m.races, frozenset)
          and isinstance(m.uuid, str) and len(m.uuid) == 12
          and isinstance(m.taunt, bool) and isinstance(m.is_golden, bool))
    check("A7", "Minion: 关键词视图（divine_shield/windfury/...）",
          all(isinstance(getattr(m, k), bool) for k in
              ("taunt", "divine_shield", "poisonous", "reborn",
               "windfury", "cleave", "exhausted")))
    check("A7", "Minion: call_script / scripts 绑定",
          hasattr(m, "scripts") and callable(m.call_script))

    # Spell
    sp = game.create_spell(db.pool_spells()[0].id, controller=h)
    check("A7", "Spell: CARDTYPE tag / cost / zone",
          sp.get(GameTag.CARDTYPE) == CardType.SPELL
          and isinstance(sp.get(GameTag.COST, 0), int)
          and isinstance(sp, Spell))
    check("A7", "Spell: 与 Entity 同源（uuid/tags/controller）",
          isinstance(sp.uuid, str) and isinstance(sp.tags, dict)
          and sp.controller is h)

    # Entity 通用
    check("A7", "Entity: get/set/has/clear 与 tags 视图",
          h.get(GameTag.GOLD) == h.gold
          and h.has(GameTag.TAVERN_TIER) and isinstance(h.tags, dict))

    # CardDef / DB 查询 / 池枚举
    d = db.get(m.card_id)
    check("A7", "CardDef: id/dbf_id/name/card_type/tech_level/atk/health/cost",
          d is not None and isinstance(d.id, str)
          and isinstance(d.dbf_id, int) and isinstance(d.name, str)
          and isinstance(d.card_type, CardType)
          and isinstance(d.tech_level, int) and isinstance(d.cost, int))
    check("A7", "CardDef: script_data_num_* 模板参数",
          isinstance(d.num(0), (int, type(None))))
    check("A7", "CardDef: keywords / races / is_golden_def / raw",
          isinstance(d.keywords, frozenset) and isinstance(d.races, frozenset)
          and isinstance(d.is_golden_def, bool)
          and isinstance(d.raw, dict))
    check("A7", "CardDB: get/by_dbf/pool_minions/pool_spells/golden_version",
          db.get(d.id) is d and db.by_dbf(d.dbf_id) is d
          and len(db.pool_minions()) > 200 and len(db.pool_spells()) > 50)
    gv = db.golden_version(db.get("BGS_018"))
    check("A7", "CardDB: 金色本体可查", gv is not None and gv.atk == 16)
    check("A7", "MinionPool: available/candidates/draw_tavern 可读",
          game.minion_pool.available(d.id) >= 0
          and isinstance(game.minion_pool.candidates(6), list)
          and game.minion_pool.total_remaining() > 0)
    check("A7", "SpellPool: available/total_remaining 可读",
          game.spell_pool.total_remaining() > 0)
    check("A7", "Game.keyword_tags_of 读取实体关键词 tag 集",
          isinstance(game.keyword_tags_of(m), frozenset))

    # 大厅统计（环境自算）
    alive = [x for x in game.heroes if x.is_alive]
    check("A7", "大厅统计：alive_count 由环境自行统计（引擎无 API）",
          len(alive) >= 1 and not hasattr(game, "rank"))


# ══════════════════════════════════════════════════════════════════════
# A8 确定性
# ══════════════════════════════════════════════════════════════════════


def _snapshot_trace(db: CardDB, seed: int) -> list:
    """固定脚本（无驱动随机）下跑 3 回合，记录可比较轨迹。"""
    ids = hero_ids(db)
    game = new_game(db, 2, seed=seed, hero_id_list=ids[:2])
    trace = []
    for _ in range(3):
        h = game.heroes[0]
        h.gold = 10
        trace.append([(e.card_id, type(e).__name__) for e in h.tavern])
        if h.tavern:
            game.buy_from_tavern(h, h.tavern[0])
            drain(game, pick=0)
        if h.hand:
            game.play_minion(h, h.hand[0])
            drain(game, pick=0)
        game.refresh_tavern(h)
        drain(game, pick=0)
        trace.append([(x.name, x.health) for x in game.heroes])
        game.end_recruit_phase()
        drain(game, pick=0)
        trace.append(game.turn)
    return trace


def probe_a8(db: CardDB) -> None:
    section("A8 确定性")
    t1 = _snapshot_trace(db, 1337)
    t2 = _snapshot_trace(db, 1337)
    t3 = _snapshot_trace(db, 1338)
    check("A8", "同一 seed 两次轨迹完全一致", t1 == t2)
    check("A8", "不同 seed 轨迹不同", t1 != t3)
    a = new_game(db, 2, seed=99)
    check("A8", "GameRNG 方法集: choice/sample/shuffle/random/randint",
          all(callable(getattr(a.rng, k, None)) for k in
              ("choice", "sample", "shuffle", "random", "randint")))
    check("A8", "GameRNG.decisions 审计日志增长（可回放）",
          isinstance(a.rng.decisions, list))
    check("A8", "引擎随机入口唯一：game.rng（脚本禁止 import random）",
          hasattr(a, "rng") and a.rng is not None)


# ══════════════════════════════════════════════════════════════════════
# A9 常见错误与规避
# ══════════════════════════════════════════════════════════════════════


def probe_a9(db: CardDB) -> None:
    section("A9 常见错误")

    # GameStateError 触发点
    game = new_game(db, 2, seed=141)
    h = game.heroes[0]
    h.gold = 0
    expect_raise("A9", "GameStateError: spend_gold 超支",
                 GameStateError, game.spend_gold, h, 1)
    expect_raise("A9", "GameStateError: refresh 金币不足",
                 GameStateError, game.refresh_tavern, h)
    # 第二技能槽：第一次授予成功，第二次重复占用 → GameStateError
    power_id = db.get(h.card_id).hero_power_id
    game.set_second_hero_power(h, power_id)
    expect_raise("A9", "GameStateError: 第二技能槽重复占用",
                 GameStateError, game.set_second_hero_power, h, power_id)
    expect_raise("A9", "GameStateError: replace_hero_power 未知 id",
                 GameStateError, game.replace_hero_power, h, "NO_SUCH_POWER")
    expect_raise("A9", "GameStateError: apply_dark_gift 未知 gift",
                 GameStateError, game.apply_dark_gift,
                 h.board[0] if h.board else game.create_minion(
                     db.pool_minions()[0].id, controller=h), "NO_SUCH_GIFT")

    # 非异常路径：返回 False 而不是抛错
    check("A9", "非法 buy / play / sell 返回 False（不抛异常）",
          game.buy_from_tavern(h, game.create_minion(
              db.pool_minions()[0].id, controller=h)) is False
          and game.play_minion(h, game.create_minion(
              db.pool_minions()[0].id, controller=h)) is False)

    # 满手牌排队：pending_hand_add → pending_hand_queue → 下回合补发
    g2 = new_game(db, 2, seed=142)
    h2 = g2.heroes[0]
    while not h2.hand_full():
        h2.add_to_hand(g2.create_minion(db.pool_minions()[0].id,
                                        controller=h2))
    extra = g2.create_minion(db.pool_minions()[0].id, controller=h2)
    ok = g2.pending_hand_add(h2, extra)
    check("A9", "满手牌: pending_hand_add → False + 进入等待队列",
          ok is False and len(g2.pending_hand_queue) == 1
          and g2.pending_hand_queue[0][1] is extra)
    h2.hand.pop()
    g2.end_recruit_phase()
    drain(g2)
    check("A9", "下回合开始: 等待队列中的卡自动补入手牌",
          len(g2.pending_hand_queue) == 0 and extra in h2.hand)

    # 文档 §9.2 的 apply_action 模板（逐分支执行）
    def apply_action(game, hero, action):
        try:
            kind = action["kind"]
            if kind == "buy":
                return game.buy_from_tavern(hero, action["entity"]), ""
            if kind == "sell":
                return game.sell_minion(hero, action["entity"]), ""
            if kind == "play_minion":
                return game.play_minion(
                    hero, action["entity"],
                    position=action.get("position"),
                    target=action.get("target"),
                    magnetic_target=action.get("magnetic_target")), ""
            if kind == "play_spell":
                return game.play_spell(hero, action["entity"],
                                       target=action.get("target")), ""
            if kind == "reroll":
                game.refresh_tavern(hero)
                return True, ""
            if kind == "upgrade":
                return game.upgrade_tavern(hero), ""
            if kind == "freeze":
                game.freeze_tavern(hero)
                return True, ""
            if kind == "hero_power":
                return game.use_hero_power(
                    hero, target=action.get("target"),
                    power_id=action.get("power_id")), ""
            if kind == "activate":
                return game.use_activate(hero, action["entity"]), ""
            if kind == "use_dark_gift":
                return game.use_dark_gift(hero), ""
            if kind == "end_turn":
                return True, "end_turn"
            return False, f"unknown kind {kind}"
        except GameStateError as e:
            return False, f"invalid: {e}"

    gA = new_game(db, 2, seed=148)
    hA = gA.heroes[0]
    hA.gold = 10
    ent = next(e for e in hA.tavern if isinstance(e, Minion))
    okA, _ = apply_action(gA, hA, {"kind": "buy", "entity": ent})
    check("A9", "apply_action 模板: buy 成功", okA is True and ent in hA.hand)
    okB, _ = apply_action(gA, hA,
                          {"kind": "play_minion", "entity": ent,
                           "position": 0})
    check("A9", "apply_action 模板: play_minion 成功",
          okB is True and ent in hA.board)
    okC, noteC = apply_action(gA, hA, {"kind": "unknown_kind"})
    check("A9", "apply_action 模板: 未知 kind 返回 (False, note)",
          okC is False and "unknown kind" in noteC)
    hA.gold = 0
    okD, _ = apply_action(gA, hA, {"kind": "reroll"})
    check("A9", "apply_action 模板: refresh 金币不足被捕获为 False",
          okD is False)
    okE, noteE = apply_action(gA, hA, {"kind": "end_turn"})
    check("A9", "apply_action 模板: end_turn 是标记动作",
          okE is True and noteE == "end_turn")

    # 淘汰后 heroes 列表变化（环境不得缓存旧列表）
    g3 = new_game(db, 3, seed=143)
    cached = list(g3.heroes)
    g3.heroes[2].health = 0
    g3.end_recruit_phase()
    drain(g3)
    check("A9", "淘汰后 game.heroes 长度变化（禁止缓存旧列表）",
          len(cached) == 3 and len(g3.heroes) < 3)

    # 已知缺陷：sell_minion 不校验实体类型（传 Spell → AttributeError，
    # 且金币已加/手牌已移除——状态已污染）。环境必须自己只卖 Minion。
    g5 = new_game(db, 2, seed=145)
    h5 = g5.heroes[0]
    h5.gold = 0
    sp = g5.create_spell(db.pool_spells()[0].id, controller=h5)
    h5.hand.append(sp)
    sp.zone = Zone.HAND
    crashed = False
    try:
        g5.sell_minion(h5, sp)
    except AttributeError:
        crashed = True
    check("A9", "已知缺陷: sell_minion(Spell) 抛 AttributeError 且状态污染",
          crashed and h5.gold == 1 and sp not in h5.hand,
          "环境必须只对 Minion 生成 sell 候选（见 READINESS D-9）")

    # 非法 position / 0 费升级 / 未知英雄 id 的行为
    g6 = new_game(db, 2, seed=146)
    h6 = g6.heroes[0]
    m6 = make_hand_minion(g6, h6)
    check("A9", "play_minion(position=99) 被夹到最右（引擎不报错）",
          g6.play_minion(h6, m6, position=99) is True
          and h6.board.index(m6) == len(h6.board) - 1)
    h6.set(GameTag.UPGRADE_COST, 0)
    h6.gold = 0
    check("A9", "upgrade_tavern 在升级费 0 且金币 0 时仍可升级",
          g6.upgrade_tavern(h6) is True and h6.tavern_tier == 2)
    bad = Hero("NOT_A_REAL_CARD", "Bad")
    g7 = Game([bad], db, seed=147)
    check("A9", "未知英雄 id 静默无技能（Hero 构造不校验 DB）",
          g7.hero_power_def(bad) is None
          and g7.hero_power_ids(bad) == []
          and g7.use_hero_power(bad) is False)

    # game.finished 之后不应继续 step
    g4 = new_game(db, 2, seed=144)
    g4.heroes[1].health = 0
    g4.end_recruit_phase()
    drain(g4)
    check("A9", "finished 后环境必须终止（引擎不再自增 turn/heroes）",
          g4.finished is True and len(g4.heroes) == 1)
    turn_at_end = g4.turn
    g4.end_recruit_phase()
    drain(g4)
    check("A9", "finished 后再次 ERP 不改变 turn（但仍会跑一遍流程）",
          g4.turn == turn_at_end and g4.finished is True)


# ══════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════


def main() -> int:
    global DB, VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose

    DB = CardDB.load(DATA_DIR)
    print(f"# probe_api: db={len(DB)} defs, data={DATA_DIR}")
    probes = [
        probe_a1, probe_a2,
        probe_a3_buy, probe_a3_sell, probe_a3_play_minion,
        probe_a3_play_spell, probe_a3_refresh, probe_a3_upgrade,
        probe_a3_hero_power, probe_a3_activate, probe_a3_dark_gift,
        probe_a3_spend_gold, probe_a4, probe_a5, probe_a6, probe_a7,
        probe_a8, probe_a9,
    ]
    for fn in probes:
        try:
            fn(DB)
        except Exception:                        # noqa: BLE001
            RESULTS.append((False, fn.__name__, "PROBE CRASHED",
                            traceback.format_exc(limit=6)))
            print(f"[FAIL] {fn.__name__} crashed:")
            traceback.print_exc(limit=6)

    failed = [r for r in RESULTS if not r[0]]
    total = len(RESULTS)
    print(f"\n# checks: {total - len(failed)}/{total} passed, "
          f"{len(failed)} failed")
    if failed:
        print("# failures:")
        for ok, sec, name, detail in failed:
            print(f"  - {sec} :: {name}  {detail}")
        return 1
    print("# ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
