"""环境适配层：把 `hsbg_engine.Game` / 自定义 env 收敛成搜索用的最小接口。

设计约束（docs/AZ_MCTS_SELFPLAY_DESIGN.md D3，本任务 task-2 要求）：
- **决策输入只允许** `observe(seat)`（3227 floats + 124 cards）与 `legal_mask(seat)`；
- 本模块提供观测块解码（OBS_STD 已冻结的偏移），供 belief 先验 / 启发式评估器使用；
- 不调用 `view()`（含对手实时棋盘）或把 `state_json()` 的隐藏字段喂给决策；
  `view/state_json` 只允许出现在测试/诊断路径（本模块不调用）。

搜索只依赖下表的鸭子接口（engine `Game` 与 `toy_env.ToyGame` 都实现）：:

    copy() -> env
    observe(p) -> ObsView | (features_bytes, cards_bytes)   # engine 返回 bytes
    legal_mask(p) -> bytes | np.ndarray[bool]
    step(p, action) -> None                                  # 非法动作抛异常
    is_over() -> bool
    needs_action(p) -> bool
    placements() -> list[int]        # 1..8；0 = 未定
    bot_play(p) -> None              # 内置策略推进该座位到本回合结束
    bot_action(p) -> int             # 内置策略的单步动作（可选）
    num_players (属性/方法) / turn (属性)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# ── 冻结契约（与 docs/OBS_STD.md §2/§3/§4 一致；不随数据版本变化）─────────────
N_ACTIONS = 245
OBS_FLOATS = 3227
OBS_CARDS = 124
N_PLAYERS = 8

GLOBAL_F = 53
OPP_F = 9
N_OPP = 7
MINION_F = 31
ITEM_F = 40
N_BOARD = 7
N_HAND = 10
N_SHOP = 8

#: 浮点块偏移（由 §2 的块大小累加；tests/test_az_search.py 会校验）
SLICE_GLOBAL = (0, 53)
SLICE_QUESTS = (53, 59)
SLICE_PENDING = (59, 68)
SLICE_BOARD = (68, 285)          # 7 * 31
SLICE_HAND = (285, 685)          # 10 * 40
SLICE_SHOP = (685, 1005)         # 8 * 40
SLICE_CHOICES = (1005, 1645)     # 16 * 40
SLICE_OPPONENTS = (1645, 1708)   # 7 * 9
SLICE_OPP_BOARDS = (1708, 3227)  # 7 * 7 * 31

#: 卡牌块偏移（§4）
CARD_HERO = (0, 1)
CARD_POWERS = (1, 3)
CARD_DEITY = (3, 4)
CARD_PENDING_SOURCE = (4, 5)
CARD_QUESTS = (5, 14)
CARD_SECRETS = (14, 19)
CARD_BOARD = (19, 26)
CARD_HAND = (26, 36)
CARD_SHOP = (36, 44)
CARD_CHOICES = (44, 60)
CARD_TRINKETS = (60, 68)
CARD_OPP_HEROES = (68, 75)
CARD_OPP_BOARDS = (75, 124)

#: global 字段下标（§3.1）
G_TURN = 0
G_HERO_SELECT = 1
G_GAME_OVER = 2
G_ALIVE = 3
G_ME_ALIVE = 4
G_HEALTH = 5
G_ARMOR = 6
G_GOLD = 7
G_MAX_GOLD_BONUS = 8
G_GOLD_NEXT = 9
G_TIER = 10
G_UPGRADE_PRICE = 11
G_REFRESH_PRICE = 12
G_MINION_PRICE = 13
G_BOARD_LEN = 33
G_HAND_LEN = 34

#: 反归一化比例（§3.1 表；无需反归一化的布尔/枚举不在此表）
G_SCALE = {
    G_TURN: 20,
    G_ALIVE: 8,
    G_HEALTH: 40,
    G_ARMOR: 20,
    G_GOLD: 10,
    G_MAX_GOLD_BONUS: 5,
    G_GOLD_NEXT: 5,
    G_TIER: 6,
    G_UPGRADE_PRICE: 10,
    G_REFRESH_PRICE: 2,
    G_MINION_PRICE: 3,
    G_BOARD_LEN: 7,
    G_HAND_LEN: 10,
}

#: 动作段（与 docs/ACTION_SPACE_STD.md §2 一致）
A_END = 0
A_REFRESH = 1
A_FREEZE = 2
A_UPGRADE = 3
A_HERO_POWER = 4
A_DARK_GIFT = 6
A_CANCEL = 7
A_BUY = 8
A_SELL = 16
A_ACTIVATE = 23
A_CHOOSE = 30
A_PLAY = 46
A_MAGNETIZE = 126
A_MOVE = 196
END_TURN = A_END


# ── 观测视图与公开信息解码 ───────────────────────────────────────────────────


@dataclass(frozen=True)
class OpponentPublic:
    """一个对手座位的**公开**摘要（来自 observe 的 opponents / opponent_boards 块）。

    这些字段全部是"最近一次战斗见到/记分板公开"的信息，不含对手实时棋盘/手牌/金币。
    """

    slot: int                 # 0..6，观测里的相对槽位
    seat: int                 # 绝对座位号
    present: bool
    alive: bool
    health: int
    armor: int
    tier: int
    seen_board_len: int
    placement: int
    is_last: bool
    is_next: bool
    hero_card: int            # cards[68+slot]，0 = 未知
    seen_minions: Tuple[Tuple[int, int, int], ...] = ()  # (embedding 下标, atk, hp)

    def as_dict(self) -> dict:
        return {
            "slot": self.slot,
            "seat": self.seat,
            "present": self.present,
            "alive": self.alive,
            "health": self.health,
            "armor": self.armor,
            "tier": self.tier,
            "seen_board_len": self.seen_board_len,
            "placement": self.placement,
            "hero_card": self.hero_card,
            "seen_minions": [list(x) for x in self.seen_minions],
        }


@dataclass(frozen=True)
class PublicInfo:
    """observe(seat) 解码出的公开 + 己方可见信息（不含其他座位隐藏量）。"""

    seat: int
    turn: int
    hero_select: bool
    game_over: bool
    alive_count: int
    me_alive: bool
    health: int
    armor: int
    gold: int
    tier: int
    upgrade_price: int
    refresh_price: int
    minion_price: int
    board_len: int
    hand_len: int
    board_power: float       # 己方棋盘 atk+hp 之和（己方可见）
    shop_prices: Tuple[int, ...] = ()
    has_pending_choice: bool = False
    opponents: Tuple[OpponentPublic, ...] = ()
    lobby_races: Tuple[int, ...] = ()  # 11 bit（§3.1 offset 42..52）

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["opponents"] = [o.as_dict() for o in self.opponents]
        return d


@dataclass
class ObsView:
    """搜索/评估器看到的唯一决策输入。"""

    features: np.ndarray      # f32[3227]
    cards: np.ndarray         # i32[124]
    mask: np.ndarray          # bool[245]
    seat: int
    turn: int
    _public: Optional[PublicInfo] = field(default=None, repr=False)

    @property
    def public(self) -> PublicInfo:
        if self._public is None:
            pub = decode_public(self.features, self.cards, self.seat)
            object.__setattr__(self, "_public", pub)
        return self._public

    @property
    def n_actions(self) -> int:
        return int(self.mask.shape[0])

    @property
    def legal_indices(self) -> np.ndarray:
        return np.flatnonzero(self.mask)

    def as_dict(self) -> dict:
        return {"seat": self.seat, "turn": self.turn,
                "n_legal": int(self.mask.sum()), "public": self.public.as_dict()}


def _raw(x: float, scale: int) -> int:
    return int(round(float(x) * float(scale)))


def _slice_cards(cards: np.ndarray, block: Tuple[int, int]) -> np.ndarray:
    return cards[block[0]:block[1]]


def decode_public(features: np.ndarray, cards: np.ndarray, seat: int,
                  num_players: int = N_PLAYERS) -> PublicInfo:
    """从标准观测解码公开信息。**只读 features/cards 的公开块**。"""
    f = np.asarray(features, dtype=np.float32)
    c = np.asarray(cards, dtype=np.int32)
    if f.shape[0] < OBS_FLOATS:
        raise ValueError(f"features 需要 {OBS_FLOATS} 维，得到 {f.shape}")
    if c.shape[0] < OBS_CARDS:
        raise ValueError(f"cards 需要 {OBS_CARDS} 维，得到 {c.shape}")

    g = f[SLICE_GLOBAL[0]:SLICE_GLOBAL[1]]
    turn = _raw(g[G_TURN], 20)
    board = f[SLICE_BOARD[0]:SLICE_BOARD[1]].reshape(N_BOARD, MINION_F)
    board_power = 0.0
    for row in board:
        if row[0] > 0.5:
            board_power += float(_raw(row[1], 10) + _raw(row[2], 10))
    shop = f[SLICE_SHOP[0]:SLICE_SHOP[1]].reshape(N_SHOP, ITEM_F)
    shop_prices: List[int] = []
    for row in shop:
        if row[0] > 0.5:
            shop_prices.append(_raw(row[2], 5))
    pending = f[SLICE_PENDING[0]:SLICE_PENDING[1]]
    # pending_kinds 是 one-hot：下标 0 = "none"，所以"待选"要看 1..8 是否有位
    has_pending = bool(pending[1:].sum() > 0.5)
    opp = f[SLICE_OPPONENTS[0]:SLICE_OPPONENTS[1]].reshape(N_OPP, OPP_F)
    opp_boards = f[SLICE_OPP_BOARDS[0]:SLICE_OPP_BOARDS[1]].reshape(N_OPP, N_BOARD, MINION_F)
    opp_heroes = _slice_cards(c, CARD_OPP_HEROES)
    opp_board_cards = _slice_cards(c, CARD_OPP_BOARDS).reshape(N_OPP, N_BOARD)

    opponents: List[OpponentPublic] = []
    for k in range(N_OPP):
        row = opp[k]
        seen: List[Tuple[int, int, int]] = []
        for j in range(N_BOARD):
            m = opp_boards[k, j]
            cid = int(opp_board_cards[k, j])
            if cid > 0 and m[0] > 0.5:
                seen.append((cid, _raw(m[1], 10), _raw(m[2], 10)))
        opponents.append(OpponentPublic(
            slot=k,
            seat=_opponent_seat(seat, k, num_players),
            present=bool(row[0] > 0.5),
            alive=bool(row[1] > 0.5),
            health=_raw(row[2], 40),
            armor=_raw(row[3], 20),
            tier=_raw(row[4], 6),
            seen_board_len=_raw(row[5], 7),
            placement=_raw(row[6], 8),
            is_last=bool(row[7] > 0.5),
            is_next=bool(row[8] > 0.5),
            hero_card=int(opp_heroes[k]),
            seen_minions=tuple(seen),
        ))

    return PublicInfo(
        seat=int(seat),
        turn=turn,
        hero_select=bool(g[G_HERO_SELECT] > 0.5),
        game_over=bool(g[G_GAME_OVER] > 0.5),
        alive_count=_raw(g[G_ALIVE], 8),
        me_alive=bool(g[G_ME_ALIVE] > 0.5),
        health=_raw(g[G_HEALTH], 40),
        armor=_raw(g[G_ARMOR], 20),
        gold=_raw(g[G_GOLD], 10),
        tier=_raw(g[G_TIER], 6),
        upgrade_price=_raw(g[G_UPGRADE_PRICE], 10),
        refresh_price=_raw(g[G_REFRESH_PRICE], 2),
        minion_price=_raw(g[G_MINION_PRICE], 3),
        board_len=_raw(g[G_BOARD_LEN], 7),
        hand_len=_raw(g[G_HAND_LEN], 10),
        board_power=board_power,
        shop_prices=tuple(shop_prices),
        has_pending_choice=has_pending,
        opponents=tuple(opponents),
        lobby_races=tuple(int(x > 0.5) for x in g[42:53]),
    )


def _opponent_seat(seat: int, slot: int, num_players: int = N_PLAYERS) -> int:
    """OBS_STD §7.4：对手按相对座位序 `(seat + 1 + slot) % n`（slot=0..6）。"""
    return int((seat + 1 + slot) % num_players)


def opponent_seats(seat: int, num_players: int = N_PLAYERS) -> List[int]:
    return [_opponent_seat(seat, k, num_players) for k in range(num_players - 1)]


# ── env 适配 ────────────────────────────────────────────────────────────────


def engine_module():
    """lazy import；未安装 Rust 引擎时返回 None（本地 toy 测试可用）。"""
    try:
        import hsbg_engine  # noqa: F401
        return hsbg_engine
    except Exception:  # noqa: BLE001 - 未构建/未安装
        return None


def is_engine_game(game: Any) -> bool:
    mod = engine_module()
    return mod is not None and isinstance(game, mod.Game)


def num_actions(game: Any) -> int:
    n = getattr(game, "N_ACTIONS", None)
    if callable(n):
        n = n()
    if isinstance(n, int) and n > 0:
        return n
    return N_ACTIONS


def num_players(game: Any) -> int:
    for name in ("num_players", "n_players", "N_PLAYERS"):
        v = getattr(game, name, None)
        if callable(v):
            try:
                v = v()
            except TypeError:
                continue
        if isinstance(v, int) and v > 0:
            return v
    try:
        return len(game.placements())
    except Exception:  # noqa: BLE001
        return N_PLAYERS


def _to_np_obs(out: Any) -> Tuple[np.ndarray, np.ndarray]:
    """engine `observe` 返回 (bytes, bytes)；toy 返回 np 数组。

    注意 `np.asarray(bytes)` 会得到 0-d bytes 标量，必须先识别 bytes 走 frombuffer。
    """
    features, cards = out

    def _conv(x: Any, dtype: str) -> np.ndarray:
        if isinstance(x, (bytes, bytearray, memoryview)):
            return np.frombuffer(bytes(x), dtype=dtype).copy()
        arr = np.asarray(x)
        if arr.dtype == np.uint8 and arr.ndim == 1:
            return np.frombuffer(arr.tobytes(), dtype=dtype).copy()
        return arr.astype(np.float32 if dtype == "<f4" else np.int32, copy=True)

    return _conv(features, "<f4"), _conv(cards, "<i4")


def legal_mask(game: Any, seat: int) -> np.ndarray:
    m = game.legal_mask(seat)
    if isinstance(m, np.ndarray):
        if m.dtype == np.uint8 and m.ndim == 1 and m.size and m.max() <= 1:
            return m.astype(bool)
        return m.astype(bool)
    return np.frombuffer(bytes(m), dtype=np.uint8).astype(bool)


def observe(game: Any, seat: int) -> ObsView:
    """取座位观测。**这是搜索/评估的唯一状态输入**。"""
    fa, ca = _to_np_obs(game.observe(seat))
    mask = legal_mask(game, seat)
    if mask.shape[0] != num_actions(game):
        # 容忍只返回部分 mask 的实现？不：契约是完整 mask，宁可报错。
        raise ValueError(f"legal_mask 长度 {mask.shape[0]} != num_actions {num_actions(game)}")
    turn = int(round(float(fa[G_TURN]) * 20.0)) if fa.shape[0] > G_TURN else 0
    return ObsView(features=fa, cards=ca, mask=mask, seat=int(seat), turn=turn)


def obs_eval_inputs(game: Any, seat: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rust `mcts_search` 回调需要的 (features, cards, mask) NumPy 版本。"""
    fa, ca = _to_np_obs(game.observe(seat))
    mask = legal_mask(game, seat)
    return fa, ca, mask


def step(game: Any, seat: int, action: int) -> None:
    game.step(int(seat), int(action))


def is_over(game: Any) -> bool:
    return bool(game.is_over())


def needs_action(game: Any, seat: int) -> bool:
    return bool(game.needs_action(int(seat)))


def placements(game: Any) -> List[int]:
    return [int(x) for x in game.placements()]


def placement_utility(placement: int, n: int = N_PLAYERS) -> float:
    """终局名次效用 u(r)=1-2(r-1)/(n-1)；未定名次（0）→ 0。"""
    if placement <= 0 or n < 2:
        return 0.0
    return float(1.0 - 2.0 * (float(placement) - 1.0) / float(n - 1))


def terminal_value(game: Any, seat: int, n: int = 0) -> Optional[float]:
    """若该座位已终局（淘汰/对局结束），返回 utility；否则 None。"""
    n = n or num_players(game)
    try:
        place = placements(game)[seat]
    except Exception:  # noqa: BLE001
        place = 0
    if place > 0:
        return placement_utility(place, n)
    if is_over(game):
        return 0.0
    return None


def bot_action(game: Any, seat: int) -> int:
    """内置策略单步动作；没有 bot_action 的 env 回退到启发式。"""
    fn = getattr(game, "bot_action", None)
    if callable(fn):
        return int(fn(int(seat)))
    from .policy import heuristic_prior  # 延迟导入避免环

    obs = observe(game, seat)
    return int(np.argmax(heuristic_prior(obs)))


def bot_play(game: Any, seat: int) -> None:
    fn = getattr(game, "bot_play", None)
    if callable(fn):
        fn(int(seat))
        return
    # 通用回退：逐步用 bot_action 直到该座位不需要行动（限步防停摆）
    for _ in range(400):
        if is_over(game) or not needs_action(game, seat):
            return
        step(game, seat, bot_action(game, seat))


def drive_opponents(game: Any, seat: int, max_steps: int = 4000) -> None:
    """推进其它座位直到 `seat` 需要行动或对局结束。

    与 Rust 搜索核 `advance_to_seat` 同语义：搜索内对手策略 = 引擎内置 bot。
    """
    n = num_players(game)
    for _ in range(max_steps):
        if is_over(game) or needs_action(game, seat):
            return
        moved = False
        for q in range(n):
            if q != seat and needs_action(game, q):
                bot_play(game, q)
                moved = True
                break
        if not moved:
            return


# ── 开局/推进辅助（评测与测试共用）─────────────────────────────────────────


def new_engine_game(seed: int, config_json: Optional[str] = None, max_turns: int = 0):
    """建一局 8 人 engine Game；`max_turns>0` 时通过 config_json 注入回合上限。

    注意：config_json 的合法 key 由 Rust `RulesConfig` 决定；调用方要自己保证。
    """
    mod = engine_module()
    if mod is None:
        raise ImportError("hsbg_engine 未安装：cd rust && python -m pip install -e .")
    return mod.Game(int(seed), config_json)


def finish_hero_select(game: Any, max_rounds: int = 16) -> Any:
    """英雄选择阶段：每个需要行动的座位选当前第一个合法动作（Choose）。"""
    for _ in range(max_rounds):
        if int(getattr(game, "turn", 0) or 0) > 0:
            break
        acted = False
        for p in range(num_players(game)):
            if needs_action(game, p):
                mask = legal_mask(game, p)
                legal = np.flatnonzero(mask)
                if legal.size == 0:
                    continue
                game.step(p, int(legal[0]))
                acted = True
                break  # 每步只推进一个座位，避免状态机假设
        if not acted:
            break
    return game


def warmup_with_bots(game: Any, turns: int = 3, max_steps: int = 20000) -> Any:
    """用内置 bot 把对局推进到 `turn>=turns`（为 determinization 制造真实战团）。"""
    for _ in range(max_steps):
        if is_over(game):
            return game
        if int(getattr(game, "turn", 0) or 0) >= turns:
            return game
        acted = False
        for p in range(num_players(game)):
            if needs_action(game, p):
                bot_play(game, p)
                acted = True
        if not acted:
            return game
    return game
