#!/usr/bin/env python
"""运行期脚本覆盖率审计（第六件验收工具）— 抓"接线存在但从不触发"的脚本。

与现有工具的分工：
  - `audit_script_wiring` 静态检查"钩子/监听是否接线"（W1–W5）
  - 本工具**跑真实随机对局**并追踪 `Entity.call_script` 分发，统计每个
    已注册脚本类的**实际触发次数** → 暴露"钩子名正确、事件名正确，但触发
    条件永远不成立 / 脚本恒早退"的第三态（这是五件套全绿仍漏缺陷的常见面）

用法:
  python tools/audit_script_runtime_coverage.py [--games 20] [--seed 3000]
                                                [--players 8] [--strict]
`--strict` 门禁: 任一 `batch_*.py` 有 ≥3 个注册脚本类且**零触发** → exit 1
（整批死脚本；单卡零触发只报告不失败——稀有卡在 20 局内不出现是正常的）。
"""

from __future__ import annotations

import argparse
import collections
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB  # noqa: E402
from hsrl2.entity import Entity  # noqa: E402
from hsrl2.game import Game, GameStateError  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402
from hsrl2.minion import Minion  # noqa: E402
from hsrl2.scripts import REGISTRY  # noqa: E402
from hsrl2.spell import Spell  # noqa: E402
from hsrl2.tags import GameTag  # noqa: E402

FIRED: collections.Counter = collections.Counter()   # class -> calls
IN_PLAY: dict = {}          # class -> set(card_id) 实际进入过棋盘/被绑定
ANOMALY = None


def _install_trace() -> None:
    orig = Entity.call_script

    def traced(self, hook, ctx=None):
        cls = getattr(self, "scripts", None)
        if cls is not None:
            key = f"{cls.__module__.split('.')[-1]}:{cls.__name__}"
            FIRED[key] += 1
            IN_PLAY.setdefault(key, set()).add(self.card_id)
        return orig(self, hook, ctx)

    Entity.call_script = traced                       # type: ignore

    orig_play_minion = Game.play_minion
    orig_play_spell = Game.play_spell

    def mark(entity):
        cls = getattr(entity, "scripts", None)
        if cls is not None:
            key = f"{cls.__module__.split('.')[-1]}:{cls.__name__}"
            IN_PLAY.setdefault(key, set()).add(entity.card_id)

    def traced_play_minion(self, hero, minion, **kw):
        ok = orig_play_minion(self, hero, minion, **kw)
        if ok:
            mark(minion)          # 只在**打出成功**时记入（否则误报）
        return ok

    def traced_play_spell(self, hero, spell, **kw):
        ok = orig_play_spell(self, hero, spell, **kw)
        if ok:
            mark(spell)
        return ok

    Game.play_minion = traced_play_minion             # type: ignore
    Game.play_spell = traced_play_spell               # type: ignore

    orig_grant = Game.grant_trinket

    def traced_grant(self, hero, trinket_id, **kw):
        e = orig_grant(self, hero, trinket_id, **kw)
        cls = getattr(e, "scripts", None)
        if cls is not None:
            key = f"{cls.__module__.split('.')[-1]}:{cls.__name__}"
            IN_PLAY.setdefault(key, set()).add(e.card_id)
        return e

    Game.grant_trinket = traced_grant                 # type: ignore


def resolve_all(game: Game, rng: random.Random) -> None:
    n = 0
    while game.pending_choices and n < 400:
        n += 1
        choice = game.pending_choices.pop(0)
        choice.choose(rng.randrange(len(choice.options)))


def play_one(db: CardDB, seed: int, players: int, turn_cap: int = 40) -> None:
    rng = random.Random(seed)
    anomaly = ANOMALY if seed % 2 == 0 else None
    hero_ids = [d.id for d in db._by_id.values()
                if d.card_type.name == "HERO"
                and d.id.startswith(("TB_BaconShop_HERO", "BG"))]
    heroes = [Hero(rng.choice(sorted(hero_ids)), f"H{i}")
              for i in range(players)]
    game = Game(heroes, db, seed=seed, anomaly=anomaly)
    game.start_game()
    resolve_all(game, rng)
    steps = 0
    while not game.finished and game.turn < turn_cap and steps < 15000:
        steps += 1
        for hero in list(game.heroes):
            if not hero.is_alive:
                continue
            try:
                game.use_hero_power(hero)
            except GameStateError:
                pass
            resolve_all(game, rng)
            for m in list(hero.board):
                if m.has(GameTag.ACTIVATE):
                    try:
                        game.use_activate(hero, m)
                    except GameStateError:
                        pass
            resolve_all(game, rng)
            try:
                game.use_dark_gift(hero)
            except GameStateError:
                pass
            resolve_all(game, rng)
            for e in list(hero.tavern):
                if not hero.hand_full() and game.buy_from_tavern(hero, e):
                    break
            resolve_all(game, rng)
            for e in list(hero.hand):
                if isinstance(e, Minion):
                    try:
                        game.play_minion(hero, e)
                    except GameStateError:
                        pass
            resolve_all(game, rng)
            for e in list(hero.hand):
                if isinstance(e, Spell):
                    try:
                        game.play_spell(hero, e)
                    except GameStateError:
                        pass
            resolve_all(game, rng)
            if rng.random() < 0.4 and hero.gold >= hero.upgrade_cost:
                game.upgrade_tavern(hero)
            if rng.random() < 0.5:
                try:
                    game.refresh_tavern(hero)
                except GameStateError:
                    pass
            resolve_all(game, rng)
            if hero.board and rng.random() < 0.2:
                game.sell_minion(hero, rng.choice(hero.board))
            # 随机授予饰品（扩大饰品脚本触发面）
            if rng.random() < 0.25:
                pool = [d.id for d in db.trinket_offer_pool()
                        if d.id not in hero.trinkets_granted]
                if pool:
                    try:
                        game.grant_trinket(hero, rng.choice(pool))
                    except Exception:                   # noqa: BLE001
                        pass
                resolve_all(game, rng)
        game.end_recruit_phase()
        resolve_all(game, rng)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--seed", type=int, default=3000)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    global ANOMALY
    db = CardDB.load(ROOT / "data")
    from hsrl2.tags import CardType as _CT
    anomaly_pool = [k for k in REGISTRY
                    if (db.get(k) is not None
                        and db.get(k).card_type == _CT.BACON_ANOMALY)]
    ANOMALY = anomaly_pool[0] if anomaly_pool else None
    _install_trace()
    for i in range(args.games):
        play_one(db, args.seed + i, args.players)
    # 注册面: batch -> [class names]
    hook_names = ("on_summon", "on_bind", "battlecry", "deathrattle",
                  "on_sell", "rally", "start_of_combat", "end_of_turn",
                  "start_of_turn", "avenge", "activate", "on_play",
                  "hero_power", "on_transform", "target_candidates")
    batches: dict[str, set] = collections.defaultdict(set)
    for cid, cls in REGISTRY.items():
        if not any(callable(getattr(cls, h, None)) for h in hook_names):
            continue          # 纯被动/数据类（无钩子）不计
        batches[cls.__module__.split(".")[-1]].add(cls.__name__)
    dead_batches, never = [], []
    suspicious = []              # 实际进入过棋盘/被绑定，但钩子零触发
    for batch, classes in sorted(batches.items()):
        fired = [c for c in classes
                 if FIRED.get(f"{batch}:{c}", 0) > 0]
        if not fired and len(classes) >= 3:
            dead_batches.append((batch, len(classes)))
        fired_set = set(fired)
        for c in classes:
            key = f"{batch}:{c}"
            if c not in fired_set and IN_PLAY.get(key):
                suspicious.append((key, sorted(IN_PLAY[key])[:4]))
    total_cls = sum(len(v) for v in batches.values())
    fired_cls = sum(1 for k in FIRED if FIRED[k] > 0)
    print(f"games={args.games} seed={args.seed} 注册脚本类={total_cls} "
          f"触发过={fired_cls} ({100 * fired_cls / max(1, total_cls):.0f}%) "
          f"钩子分发={sum(FIRED.values())}")
    print(f"批次 {len(batches)}; 整批零触发(≥3 类): {len(dead_batches)}")
    for b, n in dead_batches:
        print(f"  [DEAD BATCH] {b}（{n} 类全部零触发）")
    print(f"从未触发（含稀有卡，仅报告）: {len(never)}")
    print()
    print(f"**可疑: 进入过棋盘/被绑定但钩子零触发** = {len(suspicious)}")
    for key, cards in suspicious[:40]:
        print(f"  [SUSPICIOUS] {key} ← {cards}")
    # 精度说明: 本工具为**报告型**——"可疑"列表需人工triage（打出失败/
    # 目标挂起/纯被动类等都会进入）。`--strict` 只做**批次级**门禁:
    # 某批 ≥3 个含钩子的脚本类全部零触发（且该批有卡被实际打出）→ exit 1。
    truly_dead = []
    for batch, classes in sorted(batches.items()):
        if len(classes) < 3:
            continue
        played = [c for c in classes if IN_PLAY.get(f"{batch}:{c}")]
        fired = [c for c in classes if FIRED.get(f"{batch}:{c}", 0) > 0]
        if played and not fired:
            truly_dead.append((batch, len(classes)))
    print(f"批次级零触发（有卡被打出但整批零钩子）: {len(truly_dead)}")
    for b, n in truly_dead:
        print(f"  [DEAD BATCH] {b}（{n} 类）")
    if args.strict and truly_dead:
        print("FAIL: 存在整批零触发的脚本批次")
        return 1
    print("PASS: 无整批零触发" if args.strict else "OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
