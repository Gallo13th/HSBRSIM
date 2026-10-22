"""Live 对局战团构造 + 战斗模拟（live turn-search 辅助层，最小可用版）。

输入是 ``tools/live_state_mem.read_live_state()``（schema ``hsbg.live_state.v1``）
的 ``board`` / ``hand`` / ``shop`` 实体列表；本模块把它们转成**引擎真实的
``Minion`` 对象**，并做无副作用的两两战斗模拟：

- :func:`build_warband`：从 live state（或实体列表）构造引擎战团；
- :func:`simulate_combat_warbands`：单场战斗（公共 seed、可复现、不修改输入）；
- :func:`pairwise_winrate`：对多个候选战团做两两战斗的胜率矩阵；
- :func:`predict_after_action`：buy/play/sell 后的 board/hand/shop **近似**
  预测（battlecry/目标效果**不执行**；只按卡面/显式 atk/hp/keywords 变化；
  文档明确标注近似）；
- :func:`make_combat_game`：最小战斗 Game（两个合成英雄，不需要完整对局）。

**不改引擎语义**：复用 ``CardDB`` + ``Game.create_minion`` + ``run_combat``；
每次模拟都新建独立 Game/战团（输入 state/构建结果不会被修改），
同 seed → 同结果。

支持的实体字段（``read_live_state`` 现行 schema；兼容嵌套 ``minion``）::

    card_id / card / id, atk, hp / health / max_hp,
    golden, keywords[list[str]], races[list[str]], tier,
    position, attached[list]（磁力模块，近似合并到宿主）

边界/近似
--------
1. **战团属性**：以 live 的 atk/hp/keywords 为准（覆盖引擎 CardDef 的基础值）；
   auras/buff 分层不保留（只保留最终数值）；多关键词按 tag 设置。
2. **race**：只设置 ``RACE`` 主种族（多类型/ALL 会警告；combat 脚本通常按
   主种族判断，完整多类型需引擎多 race 支持）。
3. **attached**（磁力模块）：把模块的 atk/hp/keywords 合并到宿主（近似）；
4. **battlecry/目标/光环效果**：``predict_after_action`` 只做区域移动，不结算
   战吼/发现/目标效果（近似；需要精确盘面时应让 live bot 真实执行后重读状态）。
5. 战斗按引擎 ``run_combat`` 精确裁决（含亡语/圣盾/风怒/剧毒等脚本）。
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

from hsbg.env import driver

__all__ = [
    "WarbandBuild",
    "CombatSimResult",
    "PairwiseResult",
    "make_combat_game",
    "normalize_entities",
    "build_warband",
    "simulate_combat_warbands",
    "pairwise_winrate",
    "predict_after_action",
]

#: live keyword 名称 → GameTag（兼容大写/空格/连字符）
_KEYWORD_ALIASES: Dict[str, str] = {
    "DIVINE_SHIELD": "DIVINE_SHIELD",
    "DIVINESHIELD": "DIVINE_SHIELD",
    "DIVINE SHIELD": "DIVINE_SHIELD",
    "TAUNT": "TAUNT",
    "POISONOUS": "POISONOUS",
    "POISON": "POISONOUS",
    "REBORN": "REBORN",
    "WINDFURY": "WINDFURY",
    "WIND_FURY": "WINDFURY",
    "MEGA_WINDFURY": "MEGA_WINDFURY",
    "MEGAWINDFURY": "MEGA_WINDFURY",
    "MEGA WINDFURY": "MEGA_WINDFURY",
    "CLEAVE": "CLEAVE",
    "MAGNETIC": "MAGNETIC",
    "BATTLECRY": "BATTLECRY",
    "DEATHRATTLE": "DEATHRATTLE",
    "RUSH": "RUSH",
    "CHARGE": "CHARGE",
}

#: 值不值得尝试设置的关键词 tag（避免把未知字符串当 tag）
_SAFE_TAGS = set(_KEYWORD_ALIASES.values())

#: live 状态里应"精确反映"的战斗可见关键词：引擎从 CardDef 初始化时会带
#: 原生关键词（如 BGS_119 自带圣盾），若 live 列表没有则应清掉；脚本类 tag
#: （BATTLECRY/DEATHRATTLE/MAGNETIC）不清，避免影响引擎的脚本分发。
_COMBAT_KEYWORD_TAGS = tuple(getattr(GameTag, name) for name in (
    "DIVINE_SHIELD", "TAUNT", "POISONOUS", "REBORN", "WINDFURY",
    "MEGA_WINDFURY", "CLEAVE"))

_RACE_BY_NAME: Dict[str, Race] = {r.name: r for r in Race}


def _card_db(db: Optional[CardDB] = None) -> CardDB:
    return db if db is not None else driver.get_card_db()


# ══════════════════════════════════════════════════════════════════════
# 实体归一化
# ══════════════════════════════════════════════════════════════════════


def _entity_dict(entity: Any) -> Dict[str, Any]:
    """live 实体 dict（兼容嵌套 ``minion``、``card`` vs ``card_id``）。"""
    if not isinstance(entity, dict):
        return {}
    out = dict(entity)
    nested = entity.get("minion")
    if isinstance(nested, dict):
        for key in ("atk", "hp", "health", "max_hp", "golden", "tier",
                    "keywords", "races", "attached", "card", "card_id"):
            if out.get(key) is None and nested.get(key) is not None:
                out[key] = nested[key]
    return out


def _entity_card_id(entity: Dict[str, Any]) -> str:
    for key in ("card_id", "card", "id"):
        value = entity.get(key)
        if value:
            return str(value)
    return ""


def _entity_int(entity: Dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = entity.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _entity_keywords(entity: Dict[str, Any]) -> List[str]:
    kws = entity.get("keywords") or []
    if isinstance(kws, dict):                          # {name: bool}
        kws = [k for k, v in kws.items() if v]
    return [str(k) for k in kws if k]


def _entity_races(entity: Dict[str, Any]) -> List[str]:
    races = entity.get("races") or []
    if isinstance(races, dict):
        races = [k for k, v in races.items() if v]
    out: List[str] = []
    for r in races:
        if isinstance(r, str):
            out.append(r)
        elif hasattr(r, "name"):
            out.append(str(r.name))
    return out


def normalize_entities(state_or_entities: Any,
                       side: str = "board") -> List[Dict[str, Any]]:
    """从 live state（dict）或实体列表取某区域实体并排序（position）。"""
    if isinstance(state_or_entities, dict):
        entities = state_or_entities.get(side) or []
    else:
        entities = state_or_entities or []
    out = [_entity_dict(e) for e in entities if isinstance(e, dict)]
    # position 优先；无 position 保持输入顺序
    if any("position" in e for e in out):
        out.sort(key=lambda e: (e.get("position") is None,
                                int(e.get("position") or 0)))
    return out


# ══════════════════════════════════════════════════════════════════════
# 最小战斗 Game / 战团构建
# ══════════════════════════════════════════════════════════════════════


def make_combat_game(db: Optional[CardDB] = None, *,
                     seed: int = 0,
                     health: int = 30, armor: int = 0,
                     health_b: Optional[int] = None,
                     armor_b: Optional[int] = None
                     ) -> Tuple[Game, Hero, Hero]:
    """构造只用于战斗的最小 ``Game``（两个合成英雄，无完整对局状态）。"""
    db = _card_db(db)
    a = Hero("LIVE_A", "LiveA")
    b = Hero("LIVE_B", "LiveB")
    game = Game([a, b], db, seed=int(seed))
    a.health = int(health)
    a.armor = int(armor)
    b.health = int(health if health_b is None else health_b)
    b.armor = int(armor if armor_b is None else armor_b)
    return game, a, b


@dataclass
class WarbandBuild:
    """构建结果：引擎 minions + 所在最小 game/hero + 输入 specs/warnings。"""

    side: str = "board"
    specs: List[Dict[str, Any]] = field(default_factory=list)
    minions: List[Minion] = field(default_factory=list)
    game: Optional[Game] = None
    hero: Optional[Hero] = None
    health: int = 30
    armor: int = 0
    tier: int = 1
    warnings: List[str] = field(default_factory=list)

    def card_ids(self) -> List[str]:
        return [str(getattr(m, "card_id", "")) for m in self.minions]

    def minion_stats(self) -> List[Dict[str, Any]]:
        return [{"card_id": str(m.card_id), "atk": int(m.atk),
                 "health": int(m.health),
                 "golden": bool(getattr(m, "is_golden", False)),
                 "keywords": sorted(k.name for k, v in m.tags.items()
                                    if v and k.name in _SAFE_TAGS)}
                for m in self.minions]


def _apply_keywords(minion: Minion, keywords: Iterable[str],
                    warnings: List[str], *, exact: bool = False) -> None:
    if exact:
        for tag in _COMBAT_KEYWORD_TAGS:
            try:
                minion.set(tag, False)
            except Exception:                         # noqa: BLE001
                pass
    for raw in keywords:
        name = str(raw).strip().upper().replace("-", "_")
        tag_name = _KEYWORD_ALIASES.get(name) or _KEYWORD_ALIASES.get(
            name.replace("_", " "))
        if not tag_name:
            warnings.append(f"unknown keyword: {raw}")
            continue
        tag = getattr(GameTag, tag_name, None)
        if tag is None:
            warnings.append(f"unknown keyword tag: {raw}")
            continue
        try:
            minion.set(tag, True)
        except Exception:                             # noqa: BLE001
            warnings.append(f"cannot set keyword: {raw}")


def _apply_races(minion: Minion, races: Iterable[str],
                 warnings: List[str]) -> None:
    names = [str(r).strip().upper() for r in races if r]
    if not names:
        return
    race = _RACE_BY_NAME.get(names[0])
    if race is None:
        warnings.append(f"unknown race: {names[0]}")
        return
    try:
        minion.set(GameTag.RACE, int(race))
    except Exception:                                 # noqa: BLE001
        warnings.append(f"cannot set race: {names[0]}")
    if len(names) > 1:
        warnings.append(f"multi-race approximated to {names[0]}: {names}")


def _apply_attached(host: Minion, attached: Iterable[Any],
                    warnings: List[str], *, exact_keywords: bool = True
                    ) -> None:
    """磁力模块：近似把模块 atk/hp/keywords 合并到宿主。"""
    extra_atk = 0
    extra_hp = 0
    keywords: List[str] = []
    for item in attached or []:
        spec = _entity_dict(item)
        if not spec:
            continue
        extra_atk += _entity_int(spec, "atk") or 0
        extra_hp += _entity_int(spec, "hp", "health", "max_hp") or 0
        keywords.extend(_entity_keywords(spec))
    if extra_atk or extra_hp:
        try:
            host.set(GameTag.BASE_ATK,
                     int(host.get(GameTag.BASE_ATK, host.atk) or 0) + extra_atk)
            host.set(GameTag.BASE_HEALTH,
                     int(host.get(GameTag.BASE_HEALTH, host.health) or 0)
                     + extra_hp)
            host.set(GameTag.HEALTH,
                     int(host.get(GameTag.HEALTH, host.health) or 0) + extra_hp)
        except Exception:                             # noqa: BLE001
            warnings.append("attached stats merge failed")
    if keywords:
        _apply_keywords(host, keywords, warnings, exact=exact_keywords)
        warnings.append("attached minions merged (approximate)")


def _make_minion(game: Game, hero: Hero, spec: Dict[str, Any],
                 warnings: List[str], *, exact_keywords: bool = True
                 ) -> Optional[Minion]:
    card_id = _entity_card_id(spec)
    if not card_id:
        warnings.append("entity without card_id")
        return None
    golden = bool(spec.get("golden", False))
    try:
        minion = game.create_minion(card_id, controller=hero,
                                    golden=golden)
    except Exception as exc:                          # noqa: BLE001
        warnings.append(f"create_minion({card_id}) failed: {exc}")
        return None
    if minion is None:
        warnings.append(f"unknown card_id: {card_id}")
        return None
    atk = _entity_int(spec, "atk")
    hp = _entity_int(spec, "hp", "health", "max_hp")
    try:
        if atk is not None:
            minion.set(GameTag.BASE_ATK, int(atk))
        if hp is not None:
            minion.set(GameTag.BASE_HEALTH, int(hp))
            minion.set(GameTag.HEALTH, int(hp))
    except Exception:                                 # noqa: BLE001
        warnings.append(f"set stats failed: {card_id}")
    tier = _entity_int(spec, "tier")
    if tier is not None:
        try:
            minion.set(GameTag.TECH_LEVEL, int(tier))
        except Exception:                             # noqa: BLE001
            pass
    _apply_keywords(minion, _entity_keywords(spec), warnings,
                    exact=exact_keywords)
    _apply_races(minion, _entity_races(spec), warnings)
    _apply_attached(minion, spec.get("attached") or [], warnings,
                    exact_keywords=exact_keywords)
    return minion


def build_warband(state_or_entities: Any = None,
                  side: str = "board", *,
                  db: Optional[CardDB] = None,
                  game: Optional[Game] = None,
                  hero: Optional[Hero] = None,
                  seed: int = 0,
                  health: Optional[int] = None,
                  armor: Optional[int] = None,
                  exact_keywords: bool = True) -> WarbandBuild:
    """从 live state/实体列表构造引擎战团（每个 spec → 真实 ``Minion``）。

    ``game``/``hero`` 未提供时创建最小战斗 Game；输入不会被修改。
    返回 :class:`WarbandBuild`（含 minions/game/hero/warnings）。
    """
    specs = normalize_entities(state_or_entities, side)
    state = state_or_entities if isinstance(state_or_entities, dict) else {}
    hp = int(health if health is not None else (state.get("health") or 30))
    ar = int(armor if armor is not None else (state.get("armor") or 0))
    tier = int(state.get("tier") or 1)
    if game is None:
        game, hero_a, _hero_b = make_combat_game(
            db, seed=seed, health=hp, armor=ar)
        hero = hero_a
    elif hero is None:
        hero = game.heroes[0]
    build = WarbandBuild(side=side, specs=specs, game=game, hero=hero,
                         health=hp, armor=ar, tier=tier)
    if hero is not None:
        hero.health = int(hp)
        hero.armor = int(ar)
        hero.board = []
    for spec in specs:
        minion = _make_minion(game, hero, spec, build.warnings,
                              exact_keywords=exact_keywords)
        if minion is None:
            continue
        try:
            hero.board.append(minion)
            minion.set(GameTag.ZONE, int(Zone.PLAY))
            minion.set(GameTag.ZONE_POSITION, len(hero.board) - 1)
        except Exception:                             # noqa: BLE001
            build.warnings.append(f"board append failed: {minion.card_id}")
            continue
        build.minions.append(minion)
    return build


# ══════════════════════════════════════════════════════════════════════
# 单场 / 两两战斗
# ══════════════════════════════════════════════════════════════════════


@dataclass
class CombatSimResult:
    """无副作用战斗结果（winner_side: "a"/"b"/"draw"）。"""

    winner_side: str = "draw"
    damage_dealt: int = 0
    capped_damage: int = 0
    rounds: int = 0
    a_health_after: int = 0
    b_health_after: int = 0
    a_armor_after: int = 0
    b_armor_after: int = 0
    a_board_after: List[Dict[str, Any]] = field(default_factory=list)
    b_board_after: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "winner_side": self.winner_side,
            "damage_dealt": int(self.damage_dealt),
            "capped_damage": int(self.capped_damage),
            "rounds": int(self.rounds),
            "a_health_after": int(self.a_health_after),
            "b_health_after": int(self.b_health_after),
            "a_armor_after": int(self.a_armor_after),
            "b_armor_after": int(self.b_armor_after),
            "a_board_after": list(self.a_board_after),
            "b_board_after": list(self.b_board_after),
            "warnings": list(self.warnings),
        }


def _board_after(hero: Hero) -> List[Dict[str, Any]]:
    return [{"card_id": str(m.card_id), "atk": int(m.atk),
             "health": int(m.health),
             "golden": bool(getattr(m, "is_golden", False))}
            for m in getattr(hero, "board", []) if not getattr(m, "dead", False)]


def simulate_combat_warbands(a: Any, b: Any, *,
                             seed: int = 0,
                             alive_count: int = 8,
                             damage_cap: Optional[int] = None,
                             a_health: Optional[int] = None,
                             b_health: Optional[int] = None,
                             a_armor: Optional[int] = None,
                             b_armor: Optional[int] = None,
                             db: Optional[CardDB] = None) -> CombatSimResult:
    """单场战斗（公共 seed；输入可为 live state/实体列表/WarbandBuild）。

    每次调用都**新建**最小 Game 与 minion（不修改输入）；同 seed 同输入 →
    同结果。``damage_cap`` 非空时调用 ``game.set_damage_cap``。
    """
    db = _card_db(db)
    game, hero_a, hero_b = make_combat_game(
        db, seed=int(seed),
        health=int(a_health if a_health is not None else 30),
        armor=int(a_armor if a_armor is not None else 0),
        health_b=int(b_health if b_health is not None else 30),
        armor_b=int(b_armor if b_armor is not None else 0))
    warnings: List[str] = []
    if isinstance(a, WarbandBuild):
        a_health = int(a.health if a_health is None else a_health)
        a_armor = int(a.armor if a_armor is None else a_armor)
        a = a.specs
    if isinstance(b, WarbandBuild):
        b_health = int(b.health if b_health is None else b_health)
        b_armor = int(b.armor if b_armor is None else b_armor)
        b = b.specs
    build_a = build_warband(a, "board", db=db, game=game, hero=hero_a,
                            seed=seed, health=a_health, armor=a_armor)
    build_b = build_warband(b, "board", db=db, game=game, hero=hero_b,
                            seed=seed, health=b_health, armor=b_armor)
    warnings.extend(build_a.warnings)
    warnings.extend(build_b.warnings)
    if damage_cap is not None:
        try:
            game.set_damage_cap(int(damage_cap))
        except Exception as exc:                      # noqa: BLE001
            warnings.append(f"set_damage_cap failed: {exc}")
    try:
        from hsrl2.combat import CombatResult  # noqa: F401
        result = game.run_combat(hero_a, hero_b,
                                 alive_count=int(alive_count))
    except Exception as exc:                          # noqa: BLE001
        warnings.append(f"run_combat failed: {type(exc).__name__}: {exc}")
        return CombatSimResult(warnings=warnings)
    winner = getattr(result, "winner", None)
    if winner is hero_a:
        winner_side = "a"
    elif winner is hero_b:
        winner_side = "b"
    else:
        winner_side = "draw"
    return CombatSimResult(
        winner_side=winner_side,
        damage_dealt=int(getattr(result, "damage_dealt", 0) or 0),
        capped_damage=int(getattr(result, "capped_damage", 0) or 0),
        rounds=int(getattr(result, "rounds", 0) or 0),
        a_health_after=int(hero_a.health),
        b_health_after=int(hero_b.health),
        a_armor_after=int(hero_a.armor),
        b_armor_after=int(hero_b.armor),
        a_board_after=_board_after(hero_a),
        b_board_after=_board_after(hero_b),
        warnings=warnings,
    )


@dataclass
class PairwiseResult:
    """两两胜率矩阵（matrix[i][j] = i 对 j 的胜率；平局计 0.5）。"""

    matrix: List[List[float]] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    n_combats: int = 0
    samples: int = 1
    seed: int = 0
    warnings: List[str] = field(default_factory=list)

    def best_index(self) -> int:
        if not self.scores:
            return -1
        return max(range(len(self.scores)), key=lambda i: self.scores[i])


def pairwise_winrate(warbands: Sequence[Any], *,
                     seed: int = 0,
                     samples: int = 1,
                     alive_count: int = 8,
                     damage_cap: Optional[int] = None,
                     db: Optional[CardDB] = None) -> PairwiseResult:
    """多个候选战团两两战斗（公共 seed，无副作用）。

    ``warbands`` 每项可为 live state/实体列表/WarbandBuild。第 (i,j) 对使用
    派生 seed ``seed + i*1009 + j*9176 + k*31``（与 turn-search 同风格），
    保证跨调用/跨进程可复现，且不依赖调用顺序外的全局状态。
    """
    items = list(warbands)
    n = len(items)
    mat = [[0.0] * n for _ in range(n)]
    samples = max(1, int(samples))
    n_combats = 0
    warnings: List[str] = []
    for i in range(n):
        for j in range(i + 1, n):
            wins = 0.0
            for k in range(samples):
                pair_seed = int(seed) + i * 1009 + j * 9176 + k * 31
                res = simulate_combat_warbands(
                    items[i], items[j], seed=pair_seed,
                    alive_count=alive_count, damage_cap=damage_cap,
                    db=db)
                n_combats += 1
                if res.winner_side == "a":
                    wins += 1.0
                elif res.winner_side == "draw":
                    wins += 0.5
                if res.warnings:
                    warnings.extend(res.warnings)
            rate = wins / samples
            mat[i][j] = rate
            mat[j][i] = 1.0 - rate
    scores = [sum(mat[i][j] for j in range(n) if j != i) / max(1, n - 1)
              for i in range(n)]
    return PairwiseResult(matrix=mat, scores=scores, n_combats=n_combats,
                          samples=samples, seed=int(seed),
                          warnings=warnings[:50])


# ══════════════════════════════════════════════════════════════════════
# 动作后的盘面近似预测（buy/play/sell）
# ══════════════════════════════════════════════════════════════════════


def _state_lists(state: Dict[str, Any]) -> Tuple[List[Any], List[Any],
                                                 List[Any]]:
    return (list(state.get("board") or []), list(state.get("hand") or []),
            list(state.get("shop") or []))


def predict_after_action(state: Dict[str, Any], action: Any, *,
                         side: str = "board") -> Dict[str, Any]:
    """buy/play/sell 后的 board/hand/shop **近似**状态（不执行战吼/目标）。

    ``action`` 支持 dict::

        {"kind": "buy", "shop_index": i}
        {"kind": "play", "hand_index": i, "position": p?}
        {"kind": "sell", "board_index": i}

    返回深拷贝的 state（原 state 不变），并附 ``"approximations"`` 列表说明
    未结算的效果（battlecry/发现/目标/费用等）。当前只处理区域移动：
    - buy：shop[i] → hand（若 ``cost``/gold 可用会扣 gold，否则不改 gold）；
    - play：hand[i] → board（按 position 插入；spell 不改变 board）；
    - sell：board[i] 移除（不结算出售奖励/亡语）。
    """
    out = copy.deepcopy(state) if isinstance(state, dict) else {}
    notes: List[str] = []
    board, hand, shop = _state_lists(out)
    act = action if isinstance(action, dict) else {"kind": str(action)}
    kind = str(act.get("kind", "")).strip().lower().replace("-", "_")
    if kind in ("buy", "purchase"):
        idx = int(act.get("shop_index", act.get("index", -1)))
        if 0 <= idx < len(shop):
            item = shop.pop(idx)
            ent = _entity_dict(item)
            cost = _entity_int(ent, "cost")
            gold = out.get("gold")
            if cost is not None and isinstance(gold, int) and gold >= cost:
                out["gold"] = gold - cost
            hand.append(item)
            notes.append("buy: moved shop→hand; cost/gold approximated")
    elif kind in ("play", "play_minion"):
        idx = int(act.get("hand_index", act.get("index", -1)))
        if 0 <= idx < len(hand):
            item = _entity_dict(hand[idx])
            # spell/item 没有 minion 字段且 CardDB 判定为法术 → 不改 board
            nested = item.get("minion")
            card_id = _entity_card_id(item)
            is_spell = bool(item.get("is_spell"))
            if nested is None and not is_spell:
                try:
                    db = _card_db()
                    d = db.get(card_id)
                    is_spell = bool(d is not None and getattr(
                        d, "is_pool_spell", False))
                except Exception:                     # noqa: BLE001
                    pass
            if is_spell:
                notes.append("play spell: board 不变（battlecry/目标不执行）")
            else:
                moved = hand.pop(idx)
                pos = act.get("position")
                try:
                    pos = int(pos) if pos is not None else -1
                except (TypeError, ValueError):
                    pos = -1
                if 0 <= pos < len(board):
                    board.insert(pos, moved)
                else:
                    board.append(moved)
                notes.append("play minion: moved hand→board; battlecry/"
                             "target/on_summon 未执行（近似）")
    elif kind in ("sell", "sell_minion"):
        idx = int(act.get("board_index", act.get("index", -1)))
        if 0 <= idx < len(board):
            board.pop(idx)
            notes.append("sell: removed board[minion]; 出售奖励/亡语未结算")
    elif kind in ("freeze", "reroll", "refresh", "upgrade", "end_turn"):
        notes.append(f"{kind}: 不影响 board/hand/shop（近似）")
    else:
        notes.append(f"unsupported action kind: {kind}（近似返回原状态）")
    # 重新编号 board position（近似：只维护槽位顺序）
    for i, ent in enumerate(board):
        if isinstance(ent, dict):
            ent["position"] = i
    out["board"] = board
    out["hand"] = hand
    out["shop"] = shop
    out["approximations"] = list(out.get("approximations") or []) + notes
    return out
