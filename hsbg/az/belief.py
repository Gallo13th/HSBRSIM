"""Determinization / 信念采样：从**公开观测**构造隐藏世界（PIMC / ISMCTS 的核心）。

诚实边界（写进 docs/AZ_IMPERFECT_SEARCH_DESIGN.md §3）：
- `EnginePublicPriorSampler` 只用 `observe(seat)` 解出的公开信息（回合、对手 tier/血量/护甲、
  最近一次见到的战团）与静态卡表（`hsbg_engine.catalog_json()`，公开数据）采样隐藏世界；
  **不读**真实隐藏状态（禁 `view` / 不拿 `state_json` 的隐藏字段做决策）。
- 具体做法：`world = game.copy()` 后，用 `debug` 命令**覆写**每个对手的隐藏量
  （board / hand / shop / gold），使 world 与观测到的公开信息一致。
  覆写后断言 `observe(seat)` 字节不变 —— 这是“公开信息保持”不变量（unit test 强制）。
- 残余泄漏（已知限制）：引擎 debug API 不能重置对手的任务/饰品/英雄技能使用次数等字段，
  这些字段仍来自真实状态。原型阶段记录在 `note`，正式版需要引擎侧
  `resample_hidden(seat, rng)` 正式接口（设计文档 §7.6）。
- 诊断用途的 `CloneSampler`（保留真实隐藏态）**只允许**用于 oracle gap 测量，不进入
  训练数据/部署；`oracle=True` 会写进结果，评测报告必须单列。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import env_api as EA


@dataclass
class DeterminizeInfo:
    """一次世界采样的元信息（写入 SearchResult.info，防误读/防泄漏）。"""

    mode: str = "unknown"
    injected_hidden: bool = False
    oracle: bool = False
    n_opponents: int = 0
    n_injections: int = 0
    obs_invariant: Optional[bool] = None
    note: str = ""
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "injected_hidden": bool(self.injected_hidden),
            "oracle": bool(self.oracle),
            "n_opponents": int(self.n_opponents),
            "n_injections": int(self.n_injections),
            "obs_invariant": self.obs_invariant,
            "note": self.note,
            "errors": list(self.errors),
        }


class BeliefSampler:
    """世界采样器协议：`sample(game, seat, rng) -> (world, DeterminizeInfo)`。"""

    name = "base"
    oracle = False

    def sample(self, game: Any, seat: int,
               rng: random.Random) -> Tuple[Any, DeterminizeInfo]:  # pragma: no cover
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - 诊断
        return f"{type(self).__name__}(name={self.name!r}, oracle={self.oracle})"


class CloneSampler(BeliefSampler):
    """保留真实隐藏态的 clone —— **仅用于 oracle gap 诊断**。"""

    name = "oracle_clone"
    oracle = True

    def sample(self, game, seat, rng):
        return game.copy(), DeterminizeInfo(
            mode="oracle_clone",
            injected_hidden=False,
            oracle=True,
            note="保留真实隐藏状态：只允许 oracle gap 诊断，禁止进入训练/部署",
        )


class PassthroughSampler(BeliefSampler):
    """无隐藏信息（或测试环境）时的直通采样：clone 即可，oracle=False。"""

    name = "passthrough"

    def sample(self, game, seat, rng):
        return game.copy(), DeterminizeInfo(
            mode="passthrough", injected_hidden=False, oracle=False,
            note="env 无隐藏信息模型（toy/测试）",
        )


class CallableSampler(BeliefSampler):
    """把 `env.determinize_world(seat, rng) -> (world, DeterminizeInfo|dict)` 包成 sampler。"""

    def __init__(self, fn: Callable, name: str = "callable"):
        self.fn = fn
        self.name = name

    def sample(self, game, seat, rng):
        out = self.fn(seat, rng)
        if isinstance(out, tuple):
            world, info = out
        else:  # pragma: no cover - 约定失败
            raise TypeError("determinize_world 必须返回 (world, DeterminizeInfo)")
        if isinstance(info, dict):
            info = DeterminizeInfo(**{k: v for k, v in info.items()
                                      if k in DeterminizeInfo.__dataclass_fields__})
        return world, info


# ── 引擎公开信息先验（本任务的主实现）───────────────────────────────────────

_CATALOG_POOLS: Optional[Dict[int, List[dict]]] = None
_CARD_ID_FROM_INDEX: Dict[int, str] = {}


def card_id_from_index(index: int) -> Optional[str]:
    """观测里的卡牌 embedding 下标（CardId+1）→ 卡 id 字符串（`add_minion` 需要）。

    只查公开卡表（`card_info`），不涉及任何对局隐藏状态。
    """
    idx = int(index)
    if idx <= 0:
        return None
    hit = _CARD_ID_FROM_INDEX.get(idx)
    if hit is not None:
        return hit
    E = _engine()
    try:
        cid = str(E.card_info(idx)[0])
    except Exception:  # noqa: BLE001 - 越界/坏下标
        return None
    _CARD_ID_FROM_INDEX[idx] = cid
    return cid


def _engine():
    mod = EA.engine_module()
    if mod is None:
        raise ImportError("hsbg_engine 未安装（cd rust && python -m pip install -e .）")
    return mod


def minion_pools() -> Dict[int, List[dict]]:
    """按 tier 分桶的可购买随从（来自公开卡表；模块级缓存，确定性顺序）。"""
    global _CATALOG_POOLS
    if _CATALOG_POOLS is not None:
        return _CATALOG_POOLS
    E = _engine()
    cat = json.loads(E.catalog_json())
    pools: Dict[int, List[dict]] = {t: [] for t in range(1, 8)}
    for c in cat:
        if c.get("kind") != "minion" or not c.get("in_pool"):
            continue
        t = int(c.get("tier", 0) or 0)
        if 1 <= t <= 6:
            pools.setdefault(t, []).append(c)
    # 确定性地排序（按 card id），保证同 seed 采样可复现
    for t in pools:
        pools[t].sort(key=lambda x: str(x.get("id", "")))
    _CATALOG_POOLS = pools
    return pools


def _sample_card(rng: random.Random, tier: int, *, shop: bool = False) -> Optional[dict]:
    """按对手酒馆等级采样一个随从（商店只出 tier<=tavern tier 的卡）。"""
    pools = minion_pools()
    hi = max(1, min(6, tier - (1 if shop else 0)))
    lo = max(1, hi - 1)
    cands: List[dict] = []
    for t in range(lo, hi + 1):
        cands.extend(pools.get(t, []))
    if not cands:
        cands = pools.get(1, [])
    if not cands:
        return None
    # 低 tier 卡更常见（近似商店概率）
    weights = [1.0 / (1.0 + 0.5 * float(c.get("tier", 1))) for c in cands]
    return rng.choices(cands, weights=weights, k=1)[0]


def _card_stats(card: dict) -> Tuple[int, int]:
    return int(card.get("atk", 1) or 1), int(card.get("hp", 1) or 1)


class EnginePublicPriorSampler(BeliefSampler):
    """从公开观测采样 8 人局的隐藏世界（PIMC / 公开信息先验 v0）。

    对每个对手：
    1. 用观测到的公开字段（tier/血量/护甲/最近战团）做条件；
    2. 以 `p_seen_board` 概率复用"最近一次见到的战团"（public），否则按 tier/turn 先验
       重新采样随从与数值；
    3. `debug` 覆写 board/hand/shop/gold（隐藏量），公开字段保持不动；
    4. 校验 `observe(seat)` 不变（公开信息保持）。
    """

    name = "engine_public_prior_v0"
    oracle = False

    def __init__(self, *, p_seen_board: float = 0.6, p_mutate: float = 0.35,
                 fill_hand: int = 2, fill_shop: int = 3,
                 max_injections: Optional[int] = None):
        self.p_seen_board = float(np.clip(p_seen_board, 0.0, 1.0))
        self.p_mutate = float(np.clip(p_mutate, 0.0, 1.0))
        self.fill_hand = int(max(0, fill_hand))
        self.fill_shop = int(max(0, fill_shop))
        self.max_injections = max_injections

    # -- 采样 helpers ---------------------------------------------------------
    def _sample_board(self, rng: random.Random, opp: EA.OpponentPublic,
                      turn: int) -> List[Tuple[Any, int, int]]:
        """返回 [(card_id_str, atk, hp), ...]（engine `add_minion` 用卡 id 字符串）。"""
        pools = minion_pools()
        tier = max(1, min(7, opp.tier or 1))
        # 规模先验：随回合增长；有公开"seen"时向它靠拢
        base = int(min(7, max(1, 1 + (turn + 1) // 3)))
        if opp.seen_board_len > 0 and rng.random() < self.p_seen_board:
            board: List[Tuple[Any, int, int]] = []
            for cid, atk, hp in opp.seen_minions:
                if cid > 0:
                    cid_s = card_id_from_index(cid)
                    if cid_s:
                        board.append((cid_s, max(1, atk), max(1, hp)))
            if not board:
                board = [(0, 0, 0)]
            # 公开战团是"上次见到"，可能已变强：以 p_mutate 替换一个随从
            if board and rng.random() < self.p_mutate:
                j = rng.randrange(len(board))
                card = _sample_card(rng, tier)
                if card is not None:
                    atk, hp = _card_stats(card)
                    board[j] = (str(card["id"]), atk, hp)
            return board[:7]
        n = max(1, min(7, base + rng.randint(-1, 1)))
        board = []
        for _ in range(n):
            card = _sample_card(rng, tier)
            if card is None:
                continue
            atk, hp = _card_stats(card)
            # 同 tier 战团强度有波动：±1 数值
            board.append((str(card["id"]), max(1, atk + rng.randint(0, 1)),
                          max(1, hp + rng.randint(0, 1))))
        return board or [("", 1, 1)]

    # -- 主流程 ---------------------------------------------------------------
    def sample(self, game, seat, rng):
        E = _engine()
        if not EA.is_engine_game(game):
            raise TypeError("EnginePublicPriorSampler 只接受 hsbg_engine.Game")
        obs_before = EA.observe(game, seat)
        pub = obs_before.public
        n_players = EA.num_players(game)
        turn = max(1, pub.turn)
        world = game.copy()
        info = DeterminizeInfo(
            mode=self.name,
            injected_hidden=True,
            oracle=False,
            n_opponents=len(pub.opponents),
            note=("按公开信息采样对手隐藏世界；残余未覆写字段（任务/饰品/技能计数）"
                  "仍来自真实状态，见设计文档 §3.4 限制"),
        )
        if self.max_injections is not None and self.max_injections <= 0:
            return world, info

        def dbg(cmd: Dict[str, Any]) -> None:
            nonlocal n_inj
            if self.max_injections is not None and n_inj >= self.max_injections:
                raise RuntimeError("max_injections reached")
            world.debug(json.dumps(cmd, ensure_ascii=False))
            n_inj += 1

        n_inj = 0
        seats = EA.opponent_seats(seat, n_players)
        for k, opp in enumerate(pub.opponents):
            if not opp.present or k >= len(seats):
                continue
            q = seats[k]
            try:
                # 1) 清空隐藏区：board / hand / shop
                for zone in ("board", "hand", "shop"):
                    dbg({"cmd": "clear_zone", "p": int(q), "zone": zone})
                # 2) 采样并写回对手战团（隐藏）
                for cid, atk, hp in self._sample_board(rng, opp, turn):
                    if not cid:
                        continue
                    dbg({"cmd": "add_minion", "p": int(q), "zone": "board",
                         "card": str(cid), "atk": int(atk), "hp": int(hp)})
                # 3) 金币（隐藏）
                gold = int(np.clip(2 + turn // 2 + rng.randint(-1, 1), 0, 10))
                dbg({"cmd": "set_player", "p": int(q), "gold": gold,
                     "free_refreshes": 0})
                # 4) 手牌（隐藏）：0..fill_hand 张
                for _ in range(rng.randint(0, self.fill_hand)):
                    card = _sample_card(rng, max(1, opp.tier))
                    if card is not None:
                        dbg({"cmd": "add_minion", "p": int(q), "zone": "hand",
                             "card": str(card["id"])})
                # 5) 商店（隐藏）：fill_shop 张（tier<=tavern tier）
                for _ in range(self.fill_shop):
                    card = _sample_card(rng, max(1, opp.tier), shop=True)
                    if card is not None:
                        dbg({"cmd": "add_minion", "p": int(q), "zone": "shop",
                             "card": str(card["id"])})
            except Exception as exc:  # noqa: BLE001 - 单个对手失败不应终止搜索
                info.errors.append(f"seat {q}: {type(exc).__name__}: {exc}")
        info.n_injections = n_inj

        # 6) 不变量：公开观测必须逐字节保持
        try:
            obs_after = EA.observe(world, seat)
            same = (obs_after.features.tobytes() == obs_before.features.tobytes()
                    and obs_after.cards.tobytes() == obs_before.cards.tobytes())
            info.obs_invariant = bool(same)
            if not same:
                # 尽力修正公开字段（health/armor/tier 是公开的，不应被采样改动）
                for k, opp in enumerate(pub.opponents):
                    if not opp.present or k >= len(seats):
                        continue
                    try:
                        world.debug(json.dumps({"cmd": "set_player", "p": int(seats[k]),
                                                "health": int(opp.health),
                                                "armor": int(opp.armor),
                                                "tier": int(opp.tier)}))
                    except Exception:  # noqa: BLE001
                        pass
                obs_after = EA.observe(world, seat)
                info.obs_invariant = bool(
                    obs_after.features.tobytes() == obs_before.features.tobytes()
                    and obs_after.cards.tobytes() == obs_before.cards.tobytes())
                info.note += "；首次注入后公开观测变化，已回写公开字段并复查"
        except Exception as exc:  # noqa: BLE001
            info.errors.append(f"obs invariance check failed: {exc}")
            info.obs_invariant = None
        return world, info


def default_sampler(game: Any) -> BeliefSampler:
    """按 env 类型选默认 sampler：

    - `hsbg_engine.Game` → `EnginePublicPriorSampler`（公开信息先验，真实 PIMC）；
    - 有 `determinize_world(seat, rng)` 的 env（toy）→ `CallableSampler`；
    - 其它 → `PassthroughSampler`（无隐藏模型）。
    """
    if EA.is_engine_game(game):
        return EnginePublicPriorSampler()
    if callable(getattr(game, "determinize_world", None)):
        return CallableSampler(game.determinize_world, name="env_determinize_world")
    return PassthroughSampler()


def split_simulations(total: int, worlds: int) -> List[int]:
    """把总模拟数尽量均匀分给 W 个世界（每世界 ≥1）。"""
    worlds = max(1, int(worlds))
    total = max(worlds, int(total))
    base, rem = divmod(total, worlds)
    return [base + (1 if w < rem else 0) for w in range(worlds)]


__all__ = [
    "BeliefSampler", "CallableSampler", "CloneSampler", "DeterminizeInfo",
    "EnginePublicPriorSampler", "PassthroughSampler", "default_sampler",
    "minion_pools", "split_simulations",
]
