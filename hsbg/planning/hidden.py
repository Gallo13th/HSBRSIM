"""隐藏状态注入（determinization v0 用；实验性，不改引擎语义）。

AlphaZero 在**隐藏信息博弈**里需要把“观测到的公开信息”扩展成若干条一致的
隐藏状态样本（世界线）。本模块提供最小注入 API（配合 ``bridge`` 的可见信息
快照使用；v0 先支持手工/采样器构造的 warband spec）：

- :func:`clear_board` / :func:`clear_hand` / :func:`clear_tavern`
- :func:`inject_minion` / :func:`inject_board` / :func:`inject_hand` /
  :func:`inject_tavern`
- :func:`inject_hidden_state`（组合；支持 ``clear=True`` 先清空）

语义/边界（v0）：

- **直接落位**（append 到 hero.board/hand/tavern + 设 ZONE/POSITION），
  **不触发** `on_summon` / 战吼 / 入场事件——避免"注入动作"被引擎当成一次
  真实召唤而改变其它状态；因此只适合在**搜索根节点**构造世界线；
- 注入建议在 :func:`hsbg.planning.model.clone` 出的副本上做（否则会改原
  对局）；本模块不自动 clone；
- 金卡/关键词/白板数值通过 ``create_minion(golden=...)`` + tag 设置实现；
- 移除旧随从只做集级清理 + 监听注销，不走 `destroy_minion`（不触发亡语，
  与"隐藏信息替换"语义一致）；若后续需要完整一致性，与 bridge 协调改为
  "先 clone 根、再在空场上注入"。

Spec 形式::

    "BG25_001"                                   # 仅卡 id
    {"card_id": "BG25_001", "golden": False,
     "atk": 3, "health": 4, "keywords": ["REBORN", "WINDFURY"]}
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Zone

__all__ = [
    "clear_board",
    "clear_hand",
    "clear_tavern",
    "inject_minion",
    "inject_board",
    "inject_hand",
    "inject_tavern",
    "inject_hidden_state",
    "normalize_spec",
]


def _unregister(game: Game, entity: Any) -> None:
    try:
        game.events.unregister_owner(entity)
    except Exception:                                     # noqa: BLE001
        pass


def clear_board(game: Game, hero: Hero) -> int:
    """清空英雄棋盘（不触发死亡/亡语；注销监听）。返回移除数量。"""
    removed = 0
    for m in list(hero.board):
        try:
            hero.board.remove(m)
        except ValueError:
            continue
        _unregister(game, m)
        removed += 1
    return removed


def clear_hand(game: Game, hero: Hero) -> int:
    removed = 0
    for e in list(getattr(hero, "hand", []) or []):
        try:
            hero.hand.remove(e)
        except ValueError:
            continue
        _unregister(game, e)
        removed += 1
    return removed


def clear_tavern(game: Game, hero: Hero) -> int:
    removed = 0
    for e in list(getattr(hero, "tavern", []) or []):
        try:
            hero.tavern.remove(e)
        except ValueError:
            continue
        _unregister(game, e)
        removed += 1
    return removed


def normalize_spec(spec: Any) -> Dict[str, Any]:
    """``str | dict`` → 统一 dict（card_id/golden/atk/health/keywords）。"""
    if isinstance(spec, str):
        return {"card_id": spec, "golden": False, "atk": None,
                "health": None, "keywords": ()}
    if isinstance(spec, dict):
        return {
            "card_id": str(spec.get("card_id") or spec.get("id") or ""),
            "golden": bool(spec.get("golden", False)),
            "atk": spec.get("atk"),
            "health": spec.get("health"),
            "keywords": tuple(spec.get("keywords", ()) or ()),
        }
    raise TypeError(f"bad hidden-state spec: {spec!r}")


def _apply_keywords(minion: Any, keywords: Iterable[str]) -> None:
    for name in keywords:
        tag = getattr(GameTag, str(name).upper(), None)
        if tag is not None:
            try:
                minion.set(tag, True)
            except Exception:                             # noqa: BLE001
                pass


def _new_minion(game: Game, hero: Hero, spec: Dict[str, Any]) -> Optional[Minion]:
    if not spec["card_id"]:
        return None
    try:
        m = game.create_minion(spec["card_id"], controller=hero,
                               golden=bool(spec["golden"]))
    except Exception:                                     # noqa: BLE001
        return None
    if spec.get("atk") is not None:
        try:
            m.set(GameTag.BASE_ATK, int(spec["atk"]))
        except Exception:                                 # noqa: BLE001
            pass
    if spec.get("health") is not None:
        try:
            m.set(GameTag.BASE_HEALTH, int(spec["health"]))
            m.set(GameTag.HEALTH, int(spec["health"]))
        except Exception:                                 # noqa: BLE001
            pass
    _apply_keywords(m, spec.get("keywords") or ())
    return m


def inject_minion(game: Game, hero: Hero, spec: Any, *,
                  zone: str = "board", position: int = -1) -> Optional[Minion]:
    """向指定区域直接放一个随从（不触发入场事件）。返回实体。"""
    norm = normalize_spec(spec)
    m = _new_minion(game, hero, norm)
    if m is None:
        return None
    if zone == "board":
        if position < 0 or position >= len(hero.board):
            hero.board.append(m)
        else:
            hero.board.insert(position, m)
        try:
            m.zone = Zone.PLAY
        except Exception:                                 # noqa: BLE001
            pass
        for i, ent in enumerate(hero.board):
            try:
                ent.set(GameTag.ZONE_POSITION, i)
            except Exception:                             # noqa: BLE001
                pass
    elif zone == "hand":
        hero.hand.append(m)
    elif zone == "tavern":
        hero.tavern.append(m)
    else:
        raise ValueError(f"unknown inject zone: {zone}")
    return m


def inject_board(game: Game, hero: Hero,
                 specs: Sequence[Any]) -> List[Minion]:
    return [m for m in (inject_minion(game, hero, s, zone="board")
                        for s in specs) if m is not None]


def inject_hand(game: Game, hero: Hero,
                specs: Sequence[Any]) -> List[Minion]:
    return [m for m in (inject_minion(game, hero, s, zone="hand")
                        for s in specs) if m is not None]


def inject_tavern(game: Game, hero: Hero,
                  specs: Sequence[Any]) -> List[Minion]:
    return [m for m in (inject_minion(game, hero, s, zone="tavern")
                        for s in specs) if m is not None]


def inject_hidden_state(game: Game, hero: Hero, *,
                        board: Optional[Sequence[Any]] = None,
                        hand: Optional[Sequence[Any]] = None,
                        tavern: Optional[Sequence[Any]] = None,
                        clear: bool = True) -> Dict[str, int]:
    """组合注入（determinization v0）：可选先清空，再按 spec 填充。

    返回各区域注入数量 ``{"board": n, "hand": n, "tavern": n}``。
    """
    out = {"board": 0, "hand": 0, "tavern": 0}
    if clear:
        clear_board(game, hero)
        clear_hand(game, hero)
        clear_tavern(game, hero)
    if board is not None:
        out["board"] = len(inject_board(game, hero, board))
    if hand is not None:
        out["hand"] = len(inject_hand(game, hero, hand))
    if tavern is not None:
        out["tavern"] = len(inject_tavern(game, hero, tavern))
    return out
