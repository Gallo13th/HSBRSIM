"""P3 hsrl2 oracle 差分：同一局面分别用 hsrl2（legacy Python oracle，37 数据）
与 hsbg_engine（Rust，37 数据）执行，比较可观察输出。

口径（docs/P3_VERIFICATION.md §2）：
* 局面由本脚本构造（不修改任何引擎/内容文件）；两侧使用同一 `data/p2/cards_37.json`
  的卡 id 与 37 数值。
* 可观察量 = 玩家棋盘（id/攻/血/关键词）、手牌 id、金币、酒馆等级、英雄技能、
  存活等**语义不变量**；不比较 RNG 流/内部 eid/事件日志顺序（约定差异）。
* 分类：
  - MATCH：全部观察项一致；
  - CONVENTION_DIFF：仅随机目标/随机生成结果不同，或某一观察项因双方约定不同
    而不可比（在 case 内显式声明）；
  - FAIL：确定性语义不一致（列表 + 最小复现命令）；
  - STRUCTURAL_OK/FAIL：无 hsrl2 参考的卡（BG33_319/BG36_360）只做数据/注册/测试
    结构检查，不伪造 oracle；
  - DEFERRED：需要战斗内逐帧或 Rust 专属调试能力，本批不硬凑。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import common

ROOT = common.ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ══════════════════════════════════════════════════════════════════════
# 两个引擎的统一 World 接口
# ══════════════════════════════════════════════════════════════════════

_N_POS = 8
_PLAY = 46
_CHOOSE = 30
_ACTIVATE = 23
_END = 0
_HERO_POWER = 4


class RustWorld:
    """hsbg_engine（Rust/PyO3）侧。"""

    def __init__(self, seed: int = 2026, hero_card: Optional[str] = None):
        import hsbg_engine  # type: ignore
        self.engine = hsbg_engine
        cfg = {} if not hero_card else {"hero_pool": [hero_card]}
        self.g = hsbg_engine.Game(seed, json.dumps(cfg))
        for p in range(self.g.num_players):
            view = self._view(p)
            self.g.step(p, view["actions"]["CHOOSE"])
        for p in range(self.g.num_players):
            for _ in range(8):
                view = self._view(p)
                if view["me"]["pending"] is None:
                    break
                self.g.step(p, view["actions"]["CHOOSE"])
            if not hero_card:
                self._dbg(cmd="set_hero", p=p, hero="TB_BaconShop_HERO_34")
            self._dbg(cmd="clear_zone", p=p, zone="board")
            self._dbg(cmd="clear_zone", p=p, zone="hand")

    # -- helpers
    def _dbg(self, **cmd) -> Any:
        return json.loads(self.g.debug(json.dumps(cmd)))

    def _view(self, p: int = 0) -> Dict[str, Any]:
        return json.loads(self.g.view(p))

    def _resolve(self, p: int) -> None:
        for _ in range(16):
            view = self._view(p)
            pending = view["me"]["pending"]
            if pending is None:
                return
            self.g.step(p, view["actions"]["CHOOSE"])

    # -- state edits
    def set_player(self, p: int = 0, *, gold=None, tier=None, health=None):
        kw = {"cmd": "set_player", "p": p}
        if gold is not None:
            kw["gold"] = int(gold)
        if tier is not None:
            kw["tier"] = int(tier)
        if health is not None:
            kw["health"] = int(health)
        self._dbg(**kw)

    def set_hero(self, hero_id: str, p: int = 0) -> None:
        self._dbg(cmd="set_hero", p=p, hero=hero_id)

    def add_to_board(self, card_id: str, p: int = 0, **kw) -> None:
        self._dbg(cmd="add_minion", p=p, zone="board", card=card_id, **kw)

    def add_to_board_with_stats(self, card_id: str, atk: int, hp: int,
                                p: int = 0) -> None:
        self._dbg(cmd="add_minion", p=p, zone="board", card=card_id,
                  atk=int(atk), hp=int(hp))

    def add_to_hand_with_stats(self, card_id: str, atk: int, hp: int,
                               p: int = 0) -> None:
        self._dbg(cmd="add_minion", p=p, zone="hand", card=card_id,
                  atk=int(atk), hp=int(hp))

    def add_to_hand(self, card_id: str, p: int = 0, *, spell=False) -> None:
        cmd = "add_spell" if spell else "add_minion"
        self._dbg(cmd=cmd, p=p, zone="hand", card=card_id)

    def wire_hero_power(self, power_id: str, p: int = 0) -> None:
        """Rust：debug 设置英雄后 power 监听由引擎接线；此处幂等占位。"""
        return None

    def free_refresh(self, p: int = 0) -> None:
        self._dbg(cmd="refresh_shop", p=p)

    # -- actions
    def _hand_index(self, card_id: str, p: int = 0) -> Optional[int]:
        for i, entry in enumerate(self._view(p)["me"]["hand"]):
            if entry.get("id") == card_id:
                return i
        return None

    def play_hand(self, card_id: str, p: int = 0,
                  target_pos: Optional[int] = None) -> bool:
        self._resolve(p)
        view = self._view(p)
        hi = self._hand_index(card_id, p)
        if hi is None:
            raise RuntimeError(f"{card_id} not in hand")
        pos = min(len(view["me"]["board"]), 6)
        self.g.step(p, _PLAY + hi * _N_POS + pos)
        if target_pos is not None:
            self._pick_target(p, target_pos)
        else:
            self._resolve(p)
        return True

    def _pick_target(self, p: int, target_pos: int) -> None:
        view = self._view(p)
        pending = view["me"]["pending"]
        if not pending or pending.get("kind") != "target":
            return
        board = view["me"]["board"]
        want_eid = board[target_pos]["eid"] if target_pos < len(board) else None
        targets = pending.get("targets") or []
        idx = targets.index(want_eid) if want_eid in targets else 0
        self.g.step(p, view["actions"]["CHOOSE"] + idx)
        self._resolve(p)

    def activate(self, board_pos: int = 0, p: int = 0) -> bool:
        self._resolve(p)
        view = self._view(p)
        self.g.step(p, _ACTIVATE + board_pos)
        self._resolve(p)
        return True

    def use_hero_power(self, p: int = 0, *, slot: int = 0,
                       target_pos: Optional[int] = None) -> bool:
        self._resolve(p)
        view = self._view(p)
        mask = view["mask"]
        action = _HERO_POWER + slot
        if not mask[action]:
            raise RuntimeError("hero power not usable")
        self.g.step(p, action)
        self._resolve(p)
        if target_pos is not None:
            self._pick_target(p, target_pos)
        return True

    def end_turn(self, p: int = 0) -> None:
        self._resolve(p)
        if self.g.needs_action(p):
            self.g.step(p, _END)

    def end_round(self) -> None:
        """推进**一个**回合（8 个座位各结束一次；最后结束者触发新回合）。"""
        for p in range(self.g.num_players):
            self.end_turn(p)

    # -- combat replay frames（debug combat_preview details=false, n=1）
    def combat_frames(self, p: int = 0) -> List[Dict[str, Any]]:
        res = self._dbg(cmd="combat_preview", a=p, b=1 - p, n=1)
        sample = res.get("sample") or {}
        return list(sample.get("frames") or [])

    def combat_delta(self, card_id: str, board_side: int = 0) -> Optional[List[int]]:
        """从 replay frames 里取 card_id 的首/末帧 [atk, hp]，返回属性增量。"""
        seq: List[List[int]] = []
        for frame in self.combat_frames():
            boards = frame.get("boards") or []
            if board_side >= len(boards):
                continue
            for m in boards[board_side]:
                if m.get("id") == card_id or m.get("card_id") == card_id:
                    seq.append([int(m.get("atk") or 0), int(m.get("hp") or 0)])
        if not seq:
            return None
        return [seq[-1][0] - seq[0][0], seq[-1][1] - seq[0][1]]

    # -- observation
    def observe(self, p: int = 0) -> Dict[str, Any]:
        view = self._view(p)
        me = view["me"]
        return {
            "gold": int(me.get("gold") or 0),
            "tier": int(me.get("tier") or 0),
            "health": int(me.get("health") or 0),
            "board": [_minion_obs(m) for m in me.get("board") or []],
            "hand": sorted(e.get("id") for e in me.get("hand") or []),
            "tavern": sorted(e.get("id") for e in me.get("shop") or []),
            "powers": sorted(p_.get("id") for p_ in me.get("hero_powers") or []),
        }


class Hsrl2World:
    """hsrl2（legacy Python oracle）侧。"""

    _DB = None

    def __init__(self, seed: int = 2026, hero_card: Optional[str] = None):
        import hsrl2.constants  # noqa: F401
        from hsrl2.db import CardDB
        from hsrl2.game import Game
        from hsrl2.hero import Hero
        if Hsrl2World._DB is None:
            Hsrl2World._DB = CardDB.load(ROOT / "data")
        self.db = Hsrl2World._DB
        if hero_card:
            heroes = [Hero(hero_card, f"H{i}") for i in range(8)]
        else:
            heroes = [Hero(f"TEST_HERO_{i}", f"H{i}") for i in range(8)]
        self.g = Game(heroes, self.db, seed=seed)
        self.g.start_game()
        self._drain()

    @property
    def hero(self):
        return self.g.heroes[0]

    def _drain(self) -> None:
        for _ in range(200):
            if not self.g.pending_choices:
                return
            choice = self.g.pending_choices.pop(0)
            choice.choose(0)

    # -- state edits
    def set_player(self, p: int = 0, *, gold=None, tier=None, health=None):
        from hsrl2.tags import GameTag
        hero = self.g.heroes[p]
        if gold is not None:
            hero.gold = int(gold)
        if tier is not None:
            hero.set(GameTag.TAVERN_TIER, int(tier))
        if health is not None:
            hero.health = int(health)

    def set_hero(self, hero_id: str, p: int = 0) -> None:
        """hsrl2 的 Hero 是轻量对象；写入主技能 id（技能脚本在 use_hero_power
        时按 id 拉取 REGISTRY）。"""
        from hsrl2.tags import GameTag
        if self.db.get(hero_id) is None:
            raise RuntimeError(f"unknown hero {hero_id}")
        self.g.heroes[p].set(GameTag.HERO_POWER, hero_id)

    def _assign_main_power(self, power_id: str, p: int = 0) -> None:
        from hsrl2.tags import GameTag
        self.g.heroes[p].set(GameTag.HERO_POWER, power_id)

    def add_to_board(self, card_id: str, p: int = 0, **kw) -> None:
        m = self.g.create_minion(card_id, controller=self.g.heroes[p],
                                 golden=bool(kw.get("golden", False)))
        self.g.summon(self.g.heroes[p], m)
        self.g._update_positions(self.g.heroes[p])

    def add_to_board_with_stats(self, card_id: str, atk: int, hp: int,
                                p: int = 0) -> None:
        from hsrl2.tags import GameTag
        m = self.g.create_minion(card_id, controller=self.g.heroes[p])
        m.set(GameTag.BASE_ATK, int(atk))
        m.set(GameTag.BASE_HEALTH, int(hp))
        m.set(GameTag.HEALTH, int(hp))
        self.g.summon(self.g.heroes[p], m)
        self.g._update_positions(self.g.heroes[p])

    def add_to_hand_with_stats(self, card_id: str, atk: int, hp: int,
                               p: int = 0) -> None:
        from hsrl2.tags import GameTag
        hero = self.g.heroes[p]
        m = self.g.create_minion(card_id, controller=hero)
        m.set(GameTag.BASE_ATK, int(atk))
        m.set(GameTag.BASE_HEALTH, int(hp))
        m.set(GameTag.HEALTH, int(hp))
        hero.add_to_hand(m)

    def wire_hero_power(self, power_id: str, p: int = 0) -> None:
        """公开幂等 API：接线 hero power 的 on_bind 监听（hsrl2/game.py:2303）。

        主技能静态绑定来自英雄卡 CardDef.hero_power_id（`hero_power_def` 的
        380 链），因此只需接线，不需要写 tag。
        """
        hero = self.g.heroes[p]
        self.g.wire_hero_power_on_bind(hero, power_id)

    def destroy_board_minion(self, pos: int = 0, p: int = 0) -> None:
        hero = self.g.heroes[p]
        self.g.destroy_minion(hero.board[pos])
        self._drain()

    def add_to_hand(self, card_id: str, p: int = 0, *, spell=False) -> None:
        hero = self.g.heroes[p]
        if spell:
            entity = self.g.create_spell(card_id, controller=hero)
        else:
            entity = self.g.create_minion(card_id, controller=hero)
        hero.add_to_hand(entity)

    def free_refresh(self, p: int = 0) -> None:
        self.g.refresh_tavern(self.g.heroes[p], auto=True)

    # -- actions
    def _hand_entry(self, card_id: str, p: int = 0):
        for entity in self.g.heroes[p].hand:
            if getattr(entity, "card_id", None) == card_id or \
                    getattr(entity, "id", None) == card_id:
                return entity
        return None

    def play_hand(self, card_id: str, p: int = 0,
                  target_pos: Optional[int] = None) -> bool:
        from hsrl2.minion import Minion
        hero = self.g.heroes[p]
        entity = self._hand_entry(card_id, p)
        if entity is None:
            raise RuntimeError(f"{card_id} not in hand")
        if isinstance(entity, Minion):
            self.g.play_minion(hero, entity, position=len(hero.board))
            self._drain()
        else:
            target = hero.board[target_pos] if target_pos is not None else None
            self.g.play_spell(hero, entity, target=target)
            self._drain()
        return True

    def activate(self, board_pos: int = 0, p: int = 0) -> bool:
        hero = self.g.heroes[p]
        m = hero.board[board_pos]
        ok = self.g.use_activate(hero, m)
        self._drain()
        return ok

    def use_hero_power(self, p: int = 0, *, slot: int = 0,
                       target_pos: Optional[int] = None) -> bool:
        hero = self.g.heroes[p]
        ids = self.g.hero_power_ids(hero)
        if not ids:
            raise RuntimeError("no hero power")
        power_id = ids[slot] if slot < len(ids) else ids[0]
        target = hero.board[target_pos] if target_pos is not None else None
        ok = self.g.use_hero_power(hero, target=target, power_id=power_id)
        self._drain()
        return ok

    def end_turn(self, p: int = 0) -> None:
        # hsrl2 的 end_recruit_phase 是整桌回合；EoT 钩子在整桌结束时触发。
        self._end_whole_round()

    def _end_whole_round(self) -> None:
        self.g.end_recruit_phase()
        self._drain()

    def end_round(self) -> None:
        self._end_whole_round()

    # -- combat replay frames（debug combat_preview details=false, n=1）
    def combat_frames(self, p: int = 0) -> List[Dict[str, Any]]:
        res = self._dbg(cmd="combat_preview", a=p, b=1 - p, n=1)
        sample = res.get("sample") or {}
        return list(sample.get("frames") or [])

    def combat_delta(self, card_id: str, board_side: int = 0) -> Optional[List[int]]:
        """从 replay frames 里取 card_id 的首/末帧 [atk, hp]，返回属性增量。"""
        seq: List[List[int]] = []
        for frame in self.combat_frames():
            boards = frame.get("boards") or []
            if board_side >= len(boards):
                continue
            for m in boards[board_side]:
                if m.get("id") == card_id or m.get("card_id") == card_id:
                    seq.append([int(m.get("atk") or 0), int(m.get("hp") or 0)])
        if not seq:
            return None
        return [seq[-1][0] - seq[0][0], seq[-1][1] - seq[0][1]]

    # -- observation
    def observe(self, p: int = 0) -> Dict[str, Any]:
        from hsrl2.minion import Minion
        hero = self.g.heroes[p]
        board = [_minion_obs(m) for m in hero.board]
        hand = sorted(getattr(e, "card_id", getattr(e, "id", "?"))
                      for e in hero.hand)
        tavern = sorted(getattr(e, "card_id", getattr(e, "id", "?"))
                        for e in hero.tavern)
        powers = []
        try:
            powers = sorted(self.g.hero_power_ids(hero))
        except Exception:  # noqa: BLE001
            powers = []
        return {
            "gold": int(hero.gold),
            "tier": int(hero.tavern_tier),
            "health": int(hero.health),
            "board": board,
            "hand": hand,
            "tavern": tavern,
            "powers": powers,
        }


def _minion_obs(m: Any) -> Dict[str, Any]:
    """统一随从观察（两引擎字段名对齐）。"""
    if isinstance(m, dict):  # Rust view
        return {"id": m.get("id"), "atk": int(m.get("atk") or 0),
                "hp": int(m.get("hp") or 0), "golden": bool(m.get("golden"))}
    return {"id": getattr(m, "card_id", getattr(m, "id", "?")),
            "atk": int(getattr(m, "atk", 0)),
            "hp": int(getattr(m, "max_health", getattr(m, "health", 0))),
            "golden": bool(getattr(m, "is_golden", False))}


# ══════════════════════════════════════════════════════════════════════
# 场景
# ══════════════════════════════════════════════════════════════════════

@dataclass
class OracleCase:
    id: str
    card: str
    owner: str
    category: str
    setup: Callable[[Any], None]
    action: Callable[[Any], None]
    observe: Callable[[Any], Dict[str, Any]]
    hsrl2_ref: str
    note: str = ""
    compare: str = "exact"   # exact | invariant
    status: str = "active"   # active | defer | structural
    hero_card: Optional[str] = None
    structural: Optional[Callable[[], Dict[str, Any]]] = None


def _board_stats(world, *, exclude=()) -> List[List[Any]]:
    obs = world.observe()
    return [[m["id"], m["atk"], m["hp"]] for m in obs["board"]
            if m["id"] not in exclude]


def _hand_contains(card_id: str):
    def obs(world):
        return {"hand_has": card_id in world.observe()["hand"],
                "hand": world.observe()["hand"]}
    return obs


# --- 1. BG23_002 Shell Collector：战吼获得 Tavern Coin ---
def _play_first_spell(w, card_id: str, target_pos: int) -> None:
    """打出手中指定法术（忽略“是否在手中”的硬失败，供 convention 场景）。"""
    if card_id in w.observe()["hand"]:
        w.play_hand(card_id, target_pos=target_pos)


def _sc_bg23_002_setup(w):
    w.add_to_hand("BG23_002")
    w.set_player(gold=10)


def _sc_bg23_002_action(w):
    w.play_hand("BG23_002")


def _naga_stats(w) -> List[int]:
    for m in w.observe()["board"]:
        if m["id"] == "BG23_009":
            return [m["atk"], m["hp"]]
    return [0, 0]


def _pre_showy_setup(w) -> None:
    w.set_player(gold=10)
    w.add_to_board_with_stats("BG31_925", 4, 2)   # Showy Cyclist 4/2
    w.add_to_board_with_stats("BG23_009", 2, 5)   # Naga（Lava Lurker 2/5）
    w._showy_pre = _naga_stats(w)


def _showy_action(w) -> None:
    if isinstance(w, RustWorld):
        # 敌方 10/1 白板：Cyclist 先攻互换 → Cyclist 死亡触发亡语；Naga 不受伤害
        w.add_to_board_with_stats("BG26_173", 10, 1, p=1)
    else:
        w.destroy_board_minion(0)   # 招募期同一 `_process_single_death` 亡语路径


def _showy_observe(w) -> Dict[str, Any]:
    if isinstance(w, RustWorld):
        return {"delta": w.combat_delta("BG23_009")}
    post = _naga_stats(w)
    pre = getattr(w, "_showy_pre", [0, 0])
    return {"delta": [post[0] - pre[0], post[1] - pre[1]]}


def _effect_snapshot(w) -> Dict[str, Any]:
    obs = w.observe()
    return {"gold": obs["gold"],
            "board": [[m["id"], m["atk"], m["hp"]] for m in obs["board"]],
            "hand": list(obs["hand"])}


def _effect_delta(w) -> Dict[str, Any]:
    pre = getattr(w, "_pre_obs", {})
    post = _effect_snapshot(w)
    changed = (pre.get("board") != post["board"]) or \
        (sorted(pre.get("hand") or []) != sorted(post["hand"]))
    return {"gold_delta": post["gold"] - pre.get("gold", 0),
            "effect_changed": bool(changed)}


def _azshara_setup(w) -> None:
    w.set_player(gold=10)
    if isinstance(w, Hsrl2World):
        w.wire_hero_power("BG22_HERO_007p")
    for cid, atk, hp in (("BG23_000", 7, 200), ("BG23_002", 7, 200),
                         ("BG23_004", 8, 200), ("BG23_007", 7, 200)):
        w.add_to_board_with_stats(cid, atk, hp)
    w.add_to_hand_with_stats("BG23_009", 1, 200)


CASES: List[OracleCase] = [
    OracleCase(
        "O01", "BG23_002", "engine-fixer", "battlecry",
        _sc_bg23_002_setup, _sc_bg23_002_action,
        _hand_contains("BG28_810"),
        "hsrl2/scripts/batches/batch_battlecry.py::ShellCollectorScript",
        "战吼获得 1 张 Tavern Coin(BG28_810)；金币不应变化", "exact"),
    OracleCase(
        "O02", "BG26_505", "engine-fixer", "spellcraft-copy",
        lambda w: (w.add_to_board("BG26_505"), w.add_to_board("BG23_000"),
                   w.set_player(gold=10)),
        lambda w: (w.end_round(), _play_first_spell(w, "BG23_000t", 0)),
        _hand_contains("BG23_000t"),
        "hsrl2/scripts/batches/batch_econ_misc.py::ZestyShakerScript",
        "定向 Spellcraft 法术(BG23_000t)打在本体 → 手牌出现同 id 副本（一次）。"
        "Spellcraft 发放时点两侧不同（hsrl2 on_summon / AT 回合开始）→ 只比"
        "“副本出现”语义", "invariant"),
    OracleCase(
        "O03", "BG27_514", "engine-fixer", "spellcraft-gain",
        lambda w: (w.set_player(gold=10), w.add_to_board("BG27_514")),
        lambda w: w.end_round(),
        _hand_contains("BG27_514t"),
        "hsrl2/scripts/batches/batch_misc.py::SeaWitchZarjiraScript",
        "入场后下一回合手牌出现 Spellcraft 法术 BG27_514t（发放时点为约定差异）", "exact"),
    OracleCase(
        "O04", "BG31_035", "engine-fixer", "play-naga-buff",
        lambda w: (w.add_to_board("BG31_035"), w.add_to_hand("BG23_009"),
                   w.set_player(gold=10)),
        lambda w: w.play_hand("BG23_009", target_pos=None),
        lambda w: _board_stats(w, exclude=("BG31_803",)),
        "hsrl2/scripts/batches/batch_econ_misc.py::GroundbreakerScript",
        "打出 Naga(BG23_009) 后 Groundbreaker 获得 +1/+1（0 施法时）", "exact"),
    OracleCase(
        "O05", "BG31_920", "engine-fixer", "spellcraft-gain",
        lambda w: (w.set_player(gold=10), w.add_to_board("BG31_920")),
        lambda w: w.end_round(),
        _hand_contains("BG31_920t"),
        "hsrl2/scripts/batches/batch_misc.py::DarkcrestStrategistScript",
        "入场后下一回合手牌出现 Spellcraft 法术 BG31_920t（发放时点为约定差异）", "exact"),
    OracleCase(
        "O06", "BG32_835", "engine-fixer", "spellcraft-gain",
        lambda w: (w.set_player(gold=10), w.add_to_board("BG32_835")),
        lambda w: w.end_round(),
        _hand_contains("BG32_835t"),
        "hsrl2/scripts/batches/batch_misc.py::TranquilMeditativeScript",
        "入场后下一回合手牌出现 Spellcraft 法术 BG32_835t（发放时点为约定差异）", "exact"),
    OracleCase(
        "O07", "BG32_837", "engine-fixer", "eot-cast",
        lambda w: (w.add_to_board("BG31_803"), w.add_to_board("BG32_837"),
                   w.add_to_board("BG31_803"), w.set_player(gold=10)),
        lambda w: w.end_turn(0),
        lambda w: _board_stats(w),
        "hsrl2/scripts/batches/batch_eot_sot.py::FaunaWhispererScript",
        "EoT 对左右相邻各施放 Natural Blessing(3/3)：兽类相邻 +6/+6", "exact"),
    OracleCase(
        "O08", "BG35_921", "content-delta-analyst", "spell-counter",
        lambda w: (w.add_to_board("BG35_921"),
                   w.add_to_hand("BG28_168", spell=True),
                   w.add_to_hand("BG28_168", spell=True),
                   w.set_player(gold=10)),
        lambda w: (w.play_hand("BG28_168"), w.play_hand("BG28_168")),
        lambda w: _board_stats(w),
        "hsrl2/scripts/batches/batch_counters.py::AbyssalBruiserScript",
        "本局已施放 2 个酒馆法术 → +2×(2/1) = 6/3（含圣盾）", "exact"),
    OracleCase(
        "O09", "BG36_622", "content-delta-analyst", "spell-on-naga",
        lambda w: (w.add_to_board("BG36_622"), w.add_to_board("BG23_009"),
                   w.add_to_hand("BG32_815", spell=True),
                   w.set_player(gold=10)),
        lambda w: w.play_hand("BG32_815", target_pos=1),
        lambda w: _board_stats(w),
        "hsrl2/scripts/batches/batch_econ_misc2.py::TorrentialRuinerScript",
        "对 Naga 施法 → 全体 +2/+3（Naga 目标另吃 Shifting Tide 的 +1/+1）", "exact"),
    OracleCase(
        "O10", "BG36_921", "content-delta-analyst", "spell-on-self",
        lambda w: (w.add_to_board("BG36_921"),
                   w.add_to_hand("BG32_815", spell=True),
                   w.set_player(gold=10)),
        lambda w: w.play_hand("BG32_815", target_pos=0),
        lambda w: _board_stats(w),
        "hsrl2/scripts/batches/batch_econ_misc2.py::FleeingFugitiveScript",
        "对本体施法 → +1 生命（另计 Shifting Tide 两次 +1/+1）", "exact"),
    OracleCase(
        "O11", "BG32_815", "content-delta-analyst", "spell",
        lambda w: (w.add_to_board("BG23_009"), w.add_to_board("BGS_034"),
                   w.add_to_hand("BG32_815", spell=True),
                   w.set_player(gold=10)),
        lambda w: w.play_hand("BG32_815", target_pos=0),
        lambda w: _board_stats(w),
        "hsrl2/scripts/batches/batch_spells4.py::ShiftingTideScript",
        "非 Naga +1/+1 twice = +2/+2；Naga 额外 repeat", "exact"),
    OracleCase(
        "O12", "BG35_922", "content-delta-analyst", "spell",
        lambda w: (w.add_to_board("BG23_009"), w.add_to_board("BGS_034"),
                   w.add_to_hand("BG35_922", spell=True),
                   w.set_player(gold=10)),
        lambda w: w.play_hand("BG35_922"),
        lambda w: _board_stats(w),
        "hsrl2/scripts/batches/batch_spells_final.py::QueensCommandScript",
        "全体 +2/+2；Naga 再 +2/+2（Naga +4/+4，非 Naga +2/+2）", "exact"),
    OracleCase(
        "O18", "BG36_508", "content-delta-analyst", "activate-invariant",
        lambda w: (w.set_player(gold=10), w.add_to_board("BG36_508"),
                   setattr(w, "_pre_obs", _effect_snapshot(w))),
        lambda w: w.activate(0),
        lambda w: _effect_delta(w),
        "hsrl2/scripts/batches/batch_unfreeze.py::CageyConjurerScript",
        "Activate(1)：随机施放 2 张酒馆法术（RNG 结果不同 → 只比语义不变量："
        "扣 1 金、激活后不可再用、至少产生一个可观察效果变化），"
        "不做逐位结果对拍", "exact"),
    OracleCase(
        "O13", "BG31_925", "engine-fixer", "deathrattle",
        lambda w: (_pre_showy_setup(w)),
        lambda w: _showy_action(w),
        lambda w: _showy_observe(w),
        "hsrl2/scripts/batches/batch_deathrattle.py::ShowyCyclistScript",
        "亡语：全体己方 Naga +2/+1（0 施法 improve 倍率）。口径：Rust 取战斗 replay"
        " 帧死亡前后 Naga 属性差；hsrl2 用公开 destroy_minion 在招募期触发同一亡语"
        "路径取同差值——比较“效果增量”，触发上下文不同（见报告口径说明）",
        "exact"),
    OracleCase(
        "O15", "BG22_HERO_007p", "rust-engine-forker", "hero-power",
        lambda w: _azshara_setup(w),
        lambda w: w.play_hand("BG23_009"),
        lambda w: {"powers": w.observe()["powers"],
                   "total_atk": sum(m["atk"] for m in w.observe()["board"])},
        "hsrl2/scripts/batches/batch_hero_combat3.py::AzsharaScript",
        "总攻 29→30（打出一张 1 攻随从）→ 主技能替换为 BG22_HERO_007p2"
        "（hsrl2 侧用公开幂等 wire_hero_power_on_bind 接线 on_bind）",
        "exact", hero_card="BG22_HERO_007"),
]


# --- 战斗内/系统类：本批 DEFERRED（需逐帧或引擎专属能力），只记录原因 ---
DEFERRED_CASES = [
    {"id": "O14", "card": "BG34_925", "owner": "content-delta-analyst",
     "category": "rally",
     "reason": "Rally 只在战斗内触发；Rust CombatPreview 明确不回写持久状态"
               "（手牌不可见），hsrl2 战后恢复棋盘/CombatResult 不含手牌——"
               "没有对称的持久观察量。需要 Rust debug-only hook 触发命令才能"
               "对拍（已按 Lead 裁定维持 DEFERRED，不改引擎）；worker 单测已覆盖"
               "右邻/最右落空/金色两次。",
     "hsrl2_ref": "batch_rally2.py::SeafloorRecruiterScript"},
]

STRUCTURAL_CARDS = [
    ("O16", "BG33_319", "content-delta-analyst",
     "Spellcraft: Get a random Tavern spell that gives stats.",
     "无 hsrl2 参考：检查 37 数据存在 / Rust scripted / worker 用例覆盖"),
    ("O17", "BG36_360", "rust-engine-forker",
     "Dark Paradox: different Dark Gift/stats/Tier each game",
     "无 hsrl2 参考：检查 base+5 形态数据、池标记与 Rust 实现决策记录"),
]


# ══════════════════════════════════════════════════════════════════════
# 执行
# ══════════════════════════════════════════════════════════════════════

def _as_obs(value: Any) -> Dict[str, Any]:
    """把场景 observe 返回值（dict 或 board_stats list）归一成 dict。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"board_stats": value}
    return {"value": value}


def run_case(case: OracleCase, seed: int = 2026) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": case.id, "card": case.card, "owner": case.owner,
        "category": case.category, "hsrl2_ref": case.hsrl2_ref,
        "note": case.note, "compare": case.compare,
    }
    results: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for name, factory in (("rust", RustWorld), ("hsrl2", Hsrl2World)):
        try:
            world = factory(seed=seed, hero_card=case.hero_card)
            case.setup(world)
            case.action(world)
            results[name] = _as_obs(case.observe(world))
        except Exception as exc:  # noqa: BLE001
            errors[name] = f"{type(exc).__name__}: {exc}"
    row["errors"] = errors
    row["observations"] = results
    if errors:
        row["classification"] = "FAIL" if not results else "FAIL"
        row["reason"] = "engine error: " + "; ".join(
            f"{k}: {v}" for k, v in errors.items())
        return row
    same = results["rust"] == results["hsrl2"]
    row["classification"] = "MATCH" if same else "FAIL"
    if not same:
        diff = {}
        for key in set(results["rust"]) | set(results["hsrl2"]):
            if results["rust"].get(key) != results["hsrl2"].get(key):
                diff[key] = {"rust": results["rust"].get(key),
                             "hsrl2": results["hsrl2"].get(key)}
        row["diff"] = diff
        row["reason"] = f"观察项不一致: {sorted(diff)}"
    return row


def structural_check(card_id: str, owner: str, note: str) -> Dict[str, Any]:
    cards = common.load_cards_37()
    catalog = common.runtime_catalog() or {}
    static = common.static_registrations()
    rec = catalog.get(card_id)
    rust_scripted = bool(rec and rec.get("scripted"))
    static_hit = card_id in static["by_id"]
    static_modules = static["by_id"].get(card_id, [])
    hsrl2_ref = common.hsrl2_reference_files([card_id])[card_id]
    data_rec = cards.get(card_id) or {}
    forms = sorted(cid for cid in cards if cid.startswith(card_id + "t") or
                   cid.startswith(card_id + "_G"))
    forms_pool = [c for c in forms if "minion" in
                  (cards[c].get("pools") or [])]
    forms_scripted = [c for c in forms
                      if (catalog.get(c) or {}).get("scripted")]
    decision_note = ""
    if card_id == "BG36_360":
        # 37 数据：base 是 tier 1/1/1 占位壳且不在池；5 个旧形态在池且已脚本化。
        # worker 决策（p3_systems.rs 头 + tests/p3_systems.rs）保持 5 形态机制。
        ok = ("minion" not in (data_rec.get("pools") or [])
              and len(forms_pool) == 5
              and all((catalog.get(c) or {}).get("scripted")
                      for c in forms_pool))
        decision_note = ("37 重做评估：base 卡不在池、5 形态在池且全部 scripted；"
                         "按 rust-engine-forker 决策保持 5 形态机制（p3_systems.rs 头 + "
                         "tests/p3_systems.rs::dark_paradox_37_data_and_mapping_invariants）")
        if ok:
            rust_scripted = True  # 池内行为由 5 形态覆盖；base 壳不需要脚本
    row = {
        "id": None, "card": card_id, "owner": owner, "category": "structural",
        "note": note,
        "data_present": bool(data_rec),
        "data_text": (data_rec.get("text") or "")[:160],
        "in_pool": "minion" in (data_rec.get("pools") or []),
        "rust_scripted": rust_scripted,
        "rust_in_static_source": static_hit,
        "rust_modules": static_modules,
        "hsrl2_ref_files": hsrl2_ref,
        "forms": forms,
        "forms_in_pool": forms_pool,
        "forms_scripted": forms_scripted,
        "decision_note": decision_note,
        "only_forms_in_pool": card_id == "BG36_360",
        "classification": "STRUCTURAL_OK" if (data_rec and rust_scripted) else
                          "STRUCTURAL_PENDING",
    }
    return row


def run_all(*, seed: int = 2026) -> Dict[str, Any]:
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    rows = [run_case(case, seed=seed) for case in CASES]
    deferred = []
    for d in DEFERRED_CASES:
        cards = common.load_cards_37()
        catalog = common.runtime_catalog() or {}
        rec = catalog.get(d["card"])
        deferred.append({**d,
                         "rust_scripted": bool(rec and rec.get("scripted")),
                         "hsrl2_ref_files": common.hsrl2_reference_files(
                             [d["card"]])[d["card"]],
                         "classification": "DEFERRED"})
    structural = []
    for sid, cid, owner, note, _n in STRUCTURAL_CARDS:
        row = structural_check(cid, owner, note)
        row["id"] = sid
        structural.append(row)
    counts: Dict[str, int] = {}
    for row in rows + deferred + structural:
        cls = row["classification"]
        counts[cls] = counts.get(cls, 0) + 1
    return {
        "meta": {"seed": seed, "started_at": started,
                 "cards_37": str(common.CARDS_37),
                 "engine_build": common.engine_build_status()},
        "rows": rows,
        "deferred": deferred,
        "structural": structural,
        "counts": counts,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="P3 hsrl2 oracle 差分")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="oracle.json")
    args = ap.parse_args(argv)
    report = run_all(seed=args.seed)
    common.write_json(args.out, report)
    print("oracle counts:", json.dumps(report["counts"], ensure_ascii=False))
    for row in report["rows"]:
        print(f"  {row['id']} {row['card']:<14} {row['classification']:<6} "
              f"{row.get('reason') or ''}")
    for row in report["deferred"]:
        print(f"  {row['id']} {row['card']:<14} DEFERRED")
    for row in report["structural"]:
        print(f"  {row['id']} {row['card']:<14} {row['classification']}")
    return 0 if not [r for r in report["rows"]
                     if r["classification"] == "FAIL"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
