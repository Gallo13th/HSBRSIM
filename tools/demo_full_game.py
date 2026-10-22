#!/usr/bin/env python
"""单局完整演示 — 只用**已迁移（REGISTRY 注册）**的脚本跑一轮真实对局并打印全过程。

与 `tools/smoke_random_games.py` 的区别:
  - 只跑**一局**，但打印**逐回合完整进程**（招募动作 / 牌桌 / 手牌 / 战斗 /
    伤害 / 淘汰 / 脚本激活追踪）
  - 追踪并汇总本次对局**实际触发了哪些已迁移脚本**（`Entity.call_script`
    钩子分发 + 事件监听器归属），并列出遇到过的**未迁移（DEFERRED/无脚本）**
    卡——它们在本局中保持"白板/未注册"状态，不产生任何效果

用法:
  python tools/demo_full_game.py [--seed 2026] [--players 8]
                                 [--turn-cap 40] [--anomaly BGxx] [--out FILE]
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

LOG: list[str] = []
TRACE = {
    "hooks": collections.Counter(),      # (batch, CardId, hook) -> n
    "listeners": collections.Counter(),  # (batch, CardId, event) -> n
    "vanilla": collections.Counter(),    # 无脚本卡（id -> 出现次数）
}


def out(line: str = "") -> None:
    LOG.append(line)
    print(line, flush=True)


def _cls_name(entity) -> str:
    cls = getattr(entity, "scripts", None)
    return cls.__name__ if cls is not None else "-"


def _batch_of(cls) -> str:
    mod = getattr(cls, "__module__", "") or ""
    return mod.split(".")[-1].replace("batch_", "")


def _batch_of_id(cid: str) -> str:
    """未绑定实体（如"发现"候选）按 id 反查其脚本所属批次。"""
    cls = REGISTRY.get(cid)
    return _batch_of(cls) if cls is not None else "-"


def install_tracing(game: Game, db: CardDB) -> None:
    orig_hook = Game.run_script_hook
    orig_fire = Entity.call_script

    def traced_call_script(self, hook, ctx=None):
        cls = getattr(self, "scripts", None)
        if cls is not None:
            TRACE["hooks"][(_batch_of(cls), self.card_id, hook)] += 1
        else:
            d = db.get(getattr(self, "card_id", None))
            if d is not None and (d.keywords or d.avenge_target
                                  or d.activate_cost is not None):
                TRACE["vanilla"][self.card_id] += 1
        return orig_fire(self, hook, ctx)

    Entity.call_script = traced_call_script            # type: ignore

    orig_register = game.events.register

    def traced_register(listener):
        owner = getattr(listener, "owner", None)
        cid = getattr(owner, "card_id", None)
        cls = getattr(owner, "scripts", None)
        if cid is not None and cls is not None:
            TRACE["listeners"][(_batch_of(cls), cid, listener.event)] += 1
        return orig_register(listener)

    game.events.register = traced_register            # type: ignore
    game._orig_run_script_hook = orig_hook             # type: ignore


def resolve_all(game: Game, rng: random.Random) -> int:
    """FIFO 解析全部 PendingChoice（`choose` 只结算不出队 → 必须 pop）。"""
    n = 0
    while game.pending_choices and n < 400:
        n += 1
        choice = game.pending_choices.pop(0)
        idx = rng.randrange(len(choice.options))
        opt = choice.options[idx]
        label = getattr(opt, "name", None) or getattr(opt, "id", None) or opt
        out(f"    · 选择 [{choice.kind}] → {label}")
        choice.choose(idx)
    return n


def describe(e, db: CardDB) -> str:
    d = db.get(getattr(e, "card_id", ""))
    name = d.name if d is not None else str(getattr(e, "card_id", "?"))
    if isinstance(e, Minion):
        extra = f"{e.atk}/{e.max_health}"
        if e.is_golden:
            extra += " 金"
        if e.get(GameTag.DIVINE_SHIELD):
            extra += " 圣盾"
        if e.get(GameTag.TAUNT):
            extra += " 嘲讽"
        if e.get(GameTag.REBORN):
            extra += " 复生"
        if e.get(GameTag.POISONOUS):
            extra += " 剧毒"
        if e.get(GameTag.VENOMOUS):
            extra += " 烈毒"
        if e.get(GameTag.WINDFURY):
            extra += " 风怒"
        return f"{name}({extra})"
    return name


def hero_line(h: Hero) -> str:
    state = "存活" if h.is_alive else "淘汰"
    return (f"{h.name} HP={h.health}+{h.armor} T{h.tavern_tier} "
            f"金={h.gold} [{state}]")


def play(db: CardDB, seed: int, players: int, turn_cap: int,
         anomaly: str | None, policy_seed: int) -> None:
    rng = random.Random(policy_seed)
    hero_ids = [d.id for d in db._by_id.values()
                if d.card_type.name == "HERO"
                and d.id.startswith(("TB_BaconShop_HERO", "BG"))]
    heroes = [Hero(rng.choice(sorted(hero_ids)), f"H{i}") for i in
              range(players)]
    game = Game(heroes, db, seed=seed, anomaly=anomaly)
    install_tracing(game, db)

    out("=" * 78)
    out(f"单局完整演示  seed={seed}  policy_seed={policy_seed}  "
        f"players={players}  异常/异变={anomaly or '无'}")
    out("脚本来源: 仅 hsrl2.scripts.REGISTRY（已迁移）；未注册卡在本局为白板")
    out("=" * 78)

    game.start_game()
    resolve_all(game, rng)
    out()
    out("【开局】")
    for h in game.heroes:
        d = db.get(h.card_id)
        power = game.hero_power_ids(h)
        pname = []
        for pid in power:
            pd = db.get(pid)
            pname.append(pd.name if pd is not None else pid)
        out(f"  {hero_line(h)}  英雄={d.name if d else h.card_id}  "
            f"技能={'/'.join(pname) or '无'}")
    out(f"  起始异变/全局钩子: {anomaly or '无'}")

    orig_combat = Game.run_combat
    combat_no = [0]

    def traced_combat(self, a, b, alive_count=None):
        combat_no[0] += 1
        # 幽灵战识别: `run_ghost_combat` 造出的临时 Hero（血量 0、名字沿用
        # 被淘汰者）——不是真实玩家，日志须区分（否则会误报"被淘汰两次"）
        ghosts = [h for h in (a, b)
                  if h.health <= 0 and h.armor <= 0]
        is_ghost = bool(ghosts)
        tag = "幽灵战" if is_ghost else "战斗"
        real = [h for h in (a, b) if h not in ghosts]
        if is_ghost:
            out()
            out(f"  ── {tag} #{combat_no[0]}  {real[0].name} vs "
                f"[幽灵] {ghosts[0].name} 的冻结战团"
                f"（T{ghosts[0].tavern_tier}）")
        else:
            out()
            out(f"  ── {tag} #{combat_no[0]}  {a.name} vs {b.name}")
        hb = {h: (h.health, h.armor) for h in (a, b)}
        res = orig_combat(self, a, b, alive_count)
        for h in real:
            dh = hb[h][0] - h.health + hb[h][1] - h.armor
            if dh:
                out(f"     {h.name} 受到 {dh} 点伤害 → HP={h.health}"
                    f"+{h.armor}")
        if res.winner is None:
            out("     结果: 平局")
        else:
            out(f"     结果: {res.winner.name} 胜（原始伤害 "
                f"{res.damage_dealt}，上限后 {res.capped_damage}）")
        if not is_ghost:
            for h in (a, b):
                if not h.is_alive:
                    out(f"     *** {h.name} 被淘汰（下回合起其战团作为"
                        f"幽灵出战）***")
        return res

    Game.run_combat = traced_combat                     # type: ignore

    turn_cap = turn_cap
    while not game.finished and game.turn < turn_cap:
        out()
        out(f"═══ 第 {game.turn} 回合 · 招募阶段 ═══")
        for hero in list(game.heroes):
            if not hero.is_alive:
                continue
            out(f"  ── {hero.name}: {hero_line(hero)}")
            used_power = False
            try:
                used_power = game.use_hero_power(hero)
            except GameStateError as e:
                out(f"     [技能落空] {e}")
            if used_power:
                out("     · 使用英雄技能")
            resolve_all(game, rng)
            for m in list(hero.board):
                if m.has(GameTag.ACTIVATE):
                    try:
                        if game.use_activate(hero, m):
                            out(f"     · Activate: {describe(m, db)}")
                    except GameStateError as e:
                        out(f"     [Activate 落空] {e}")
            resolve_all(game, rng)
            try:
                if game.use_dark_gift(hero):
                    out("     · 使用 Dark Gift")
            except GameStateError as e:
                out(f"     [Dark Gift 落空] {e}")
            resolve_all(game, rng)

            offers = [describe(e, db) for e in hero.tavern]
            out(f"     酒馆: {', '.join(offers) if offers else '（空）'}")
            bought = False
            for e in list(hero.tavern):
                if not hero.hand_full() and game.buy_from_tavern(hero, e):
                    out(f"     · 购买 {describe(e, db)}（金={hero.gold}）")
                    bought = True
                    break
            if not bought:
                out("     · 未购买（金不足 / 满手 / 无可买）")
            resolve_all(game, rng)
            for e in list(hero.hand):
                if isinstance(e, Minion):
                    try:
                        if game.play_minion(hero, e):
                            out(f"     · 打出随从 {describe(e, db)}")
                    except GameStateError as err:
                        out(f"     [打出落空] {err}")
            resolve_all(game, rng)
            for e in list(hero.hand):
                if isinstance(e, Spell):
                    try:
                        if game.play_spell(hero, e):
                            out(f"     · 施放法术 {describe(e, db)}")
                    except GameStateError as err:
                        out(f"     [施放落空] {err}")
            resolve_all(game, rng)
            if rng.random() < 0.4 and hero.gold >= hero.upgrade_cost:
                if game.upgrade_tavern(hero):
                    out(f"     · 升级酒馆 → T{hero.tavern_tier}"
                        f"（金={hero.gold}）")
            if rng.random() < 0.5:
                try:
                    game.refresh_tavern(hero)
                    out(f"     · 刷新酒馆（金={hero.gold}）")
                except GameStateError as err:
                    out(f"     [刷新落空] {err}")
            resolve_all(game, rng)
            if hero.board and rng.random() < 0.2:
                victim = rng.choice(hero.board)
                game.sell_minion(hero, victim)
                out(f"     · 出售 {describe(victim, db)}（金={hero.gold}）")
            out(f"     棋盘: {', '.join(describe(m, db) for m in hero.board)}"
                f"  手牌: {len(hero.hand)} 张")
            out(f"     饰品: {', '.join(describe(t, db) for t in hero.trinkets) or '无'}")
        game.end_recruit_phase()
        resolve_all(game, rng)
        out("  ── 回合结算后存活:")
        for h in game.heroes:
            out(f"     {hero_line(h)}")

    Game.run_combat = orig_combat                       # type: ignore
    out()
    out("=" * 78)
    out(f"【终局】turn={game.turn} finished={game.finished}")
    ranking = sorted(game.heroes, key=lambda h: (
        not h.is_alive, -game.turn, -h.health))
    for i, h in enumerate(ranking, 1):
        out(f"  第 {i} 名: {h.name} {hero_line(h)}  "
            f"英雄={db.get(h.card_id).name if db.get(h.card_id) else '?'}")
    out("=" * 78)
    out("【已迁移脚本激活统计（本局）】")
    by_batch = collections.Counter()
    for (batch, cid, hook), n in TRACE["hooks"].items():
        by_batch[batch] += n
    out(f"  钩子分发总数: {sum(TRACE['hooks'].values())}，"
        f"涉及批次 {len(by_batch)} 个，"
        f"不同卡 {len({c for _, c, _ in TRACE['hooks']})} 张")
    for batch, n in by_batch.most_common():
        cards = sorted({c for b, c, _ in TRACE["hooks"] if b == batch})
        out(f"   * {batch:22s} {n:5d} 次  ({', '.join(cards[:8])}"
            f"{' …' if len(cards) > 8 else ''})")
    out()
    out("  触发点明细（卡 × 钩子）:")
    for (batch, cid, hook), n in TRACE["hooks"].most_common(40):
        d = db.get(cid)
        out(f"   - [{batch}] {cid} {d.name if d else ''} :: {hook} × {n}")
    out()
    out("  注册的持久监听器（卡 × 事件 × 数量）:")
    for (batch, cid, event), n in TRACE["listeners"].most_common(40):
        d = db.get(cid)
        out(f"   - [{batch}] {cid} {d.name if d else ''} :: {event} × {n}")
    out()
    out(f"【未迁移（无脚本）卡在本局的接触记录】共 "
        f"{len(TRACE['vanilla'])} 张")
    for cid, n in TRACE["vanilla"].most_common(30):
        d = db.get(cid)
        out(f"   - {cid} {d.name if d else ''} × {n}（无脚本 → 白板/无效果）")
    out("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--policy-seed", type=int, default=7)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--turn-cap", type=int, default=40)
    ap.add_argument("--anomaly", type=str, default=None)
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()
    db = CardDB.load(ROOT / "data")
    play(db, args.seed, args.players, args.turn_cap, args.anomaly,
         args.policy_seed)
    if args.out:
        Path(args.out).write_text("\n".join(LOG) + "\n", encoding="utf-8")
        print(f"\n[log written to {args.out}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
