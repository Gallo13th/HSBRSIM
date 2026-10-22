"""合成观测 / 候选动作工厂（Mock 环境与测试共用）。

这里只生成**符合 ``hsbg.env.spec`` 契约**的纯数据对象，不依赖真环境层，
因此策略/训练管线可以在 env-builder 完成之前独立自测。

约定
----
* 随机性全部来自 ``numpy.random.Generator``（禁止 ``random`` 模块，见 AGENTS）。
* 实体 ``card_id`` 默认取自带的小型假词表 :data:`FAKE_CARD_IDS`；也可以传
  入真实 ``CardVocab`` 里的 id 以贴近真环境。
* 候选动作数量**变长**，偶尔超过 ``CANDIDATE_MAX``（用于测试编码器截断），
  但每个候选本身都引用存在的槽位（合法候选语义）。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

from hsbg.env.spec import (
    ActionKind,
    BOARD_MAX,
    CANDIDATE_MAX,
    CARD_TYPE_MINION,
    CARD_TYPE_QUEST,
    CARD_TYPE_SPELL,
    CARD_TYPE_TRINKET,
    CHOICE_OPTION_MAX,
    HAND_MAX,
    LobbyPlayer,
    OPPONENT_BOARD_MAX,
    PHASE_CHOICE,
    PHASE_RECRUIT,
    PLAYER_MAX,
    RACES,
    TAVERN_MAX,
    TRINKET_MAX,
    ZONE_BOARD,
    ZONE_CHOICE,
    ZONE_HAND,
    ZONE_NONE,
    ZONE_OPPONENT,
    ZONE_QUEST,
    ZONE_TAVERN,
    ZONE_TRINKET,
    CandidateAction,
    EntityToken,
    HeroToken,
    Observation,
    PendingChoice,
)
from hsbg.policy.encoder import KEYWORD_INDEX

#: 合成数据使用的假卡牌 id（编码器词表可用它构建小词表，避免依赖 data/）
FAKE_CARD_IDS: Tuple[str, ...] = tuple(
    [f"FAKE_MINION_{i:03d}" for i in range(48)]
    + [f"FAKE_SPELL_{i:03d}" for i in range(16)]
    + [f"FAKE_HERO_{i:03d}" for i in range(8)]
    + [f"FAKE_POWER_{i:03d}" for i in range(8)]
    + [f"FAKE_TRINKET_{i:03d}" for i in range(8)]
    + [f"FAKE_QUEST_{i:03d}" for i in range(4)]
)

_ALL_RACES: Tuple[str, ...] = tuple(r for r in RACES if r not in ("all", "none"))
_ALL_KEYWORDS: Tuple[str, ...] = tuple(k for k in KEYWORD_INDEX if k != "other")


# ══════════════════════════════════════════════════════════════════════
# 实体 / 大厅
# ══════════════════════════════════════════════════════════════════════


def _pick_card(rng: np.random.Generator, ids: Sequence[str], prefix: str) -> str:
    if ids and rng.random() < 0.9:
        return str(ids[int(rng.integers(0, len(ids)))])
    # 10% 未登录卡：训练/编码器应映射到 <UNK> 而不是崩溃
    return f"UNKNOWN_{prefix}_{int(rng.integers(0, 999))}"


def random_entity(
    rng: np.random.Generator,
    zone: str,
    slot: int,
    *,
    card_ids: Optional[Sequence[str]] = None,
    card_type: Optional[str] = None,
) -> EntityToken:
    """生成一个随机实体 token。"""
    if card_type is None:
        if zone == ZONE_TAVERN:
            card_type = CARD_TYPE_SPELL if rng.random() < 0.25 else CARD_TYPE_MINION
        elif zone == ZONE_TRINKET:
            card_type = CARD_TYPE_TRINKET
        elif zone == ZONE_QUEST:
            card_type = CARD_TYPE_QUEST
        elif zone == ZONE_OPPONENT:
            card_type = CARD_TYPE_MINION
        else:
            card_type = CARD_TYPE_MINION
    ids = list(card_ids) if card_ids else list(FAKE_CARD_IDS)
    n_races = int(rng.integers(0, 3))
    races = tuple(_ALL_RACES[int(i)] for i in rng.choice(len(_ALL_RACES), size=n_races, replace=False)) if n_races else ()
    n_kw = int(rng.integers(0, 3))
    keywords = tuple(
        _ALL_KEYWORDS[int(i)] for i in rng.choice(len(_ALL_KEYWORDS), size=n_kw, replace=False)
    ) if n_kw else ()
    tier = int(rng.integers(1, 7))
    atk = int(rng.integers(0, 30))
    health = int(rng.integers(0, 30))
    return EntityToken(
        card_id=_pick_card(rng, ids, zone or "x"),
        card_type=card_type,
        zone=zone,
        slot=slot,
        atk=atk,
        health=health,
        tier=tier,
        cost=int(rng.integers(0, 7)),
        races=races,
        keywords=keywords,
        golden=bool(rng.random() < 0.1),
        entity_id=int(rng.integers(1, 100000)),
        name=f"Entity_{zone}_{slot}",
    )


def random_entities(
    rng: np.random.Generator,
    zone: str,
    max_slots: int,
    *,
    max_count: Optional[int] = None,
    card_ids: Optional[Sequence[str]] = None,
) -> Tuple[EntityToken, ...]:
    count = int(rng.integers(0, min(max_slots, max_count if max_count is not None else max_slots) + 1))
    return tuple(
        random_entity(rng, zone, i, card_ids=card_ids) for i in range(count)
    )


def random_lobby(rng: np.random.Generator, num_players: int = PLAYER_MAX) -> Tuple[LobbyPlayer, ...]:
    players: List[LobbyPlayer] = []
    # 保证至少一个存活（智能体自己）
    for i in range(num_players):
        alive = i == 0 or bool(rng.random() < 0.75)
        players.append(
            LobbyPlayer(
                name=f"P{i}",
                health=int(rng.integers(0, 41)) if alive else 0,
                armor=int(rng.integers(0, 16)) if alive else 0,
                tier=int(rng.integers(1, 7)) if alive else 0,
                alive=alive,
                is_agent=(i == 0),
                eliminated_rank=0,
            )
        )
    return tuple(players)


def random_hero(
    rng: np.random.Generator, *, card_ids: Optional[Sequence[str]] = None,
) -> HeroToken:
    ids = list(card_ids) if card_ids else list(FAKE_CARD_IDS)
    return HeroToken(
        hero_id=_pick_card(rng, ids, "hero"),
        health=int(rng.integers(-5, 41)),
        armor=int(rng.integers(0, 21)),
        tier=int(rng.integers(1, 7)),
        gold=int(rng.integers(0, 13)),
        upgrade_cost=int(rng.integers(0, 13)),
        power_id=_pick_card(rng, ids, "power"),
        power_cost=int(rng.integers(0, 4)),
        power_usable=bool(rng.random() < 0.6),
    )


# ══════════════════════════════════════════════════════════════════════
# 候选动作
# ══════════════════════════════════════════════════════════════════════

#: 合成候选的动作类型清单（覆盖全部 12 种，choose 仅在 choice 阶段用）
_MOCK_KINDS: Tuple[str, ...] = tuple(k.value for k in ActionKind)


def random_candidates(
    rng: np.random.Generator,
    obs: Observation,
    *,
    count: Optional[int] = None,
    max_count: int = CANDIDATE_MAX + 6,
    choice_phase: Optional[bool] = None,
) -> Tuple[CandidateAction, ...]:
    """按当前观测生成变长合法候选列表。"""
    n_board = len(obs.board)
    n_hand = len(obs.hand)
    n_tavern = len(obs.tavern)
    n_choice = len(obs.pending_choice.options) if obs.pending_choice is not None else 0
    is_choice = (
        choice_phase
        if choice_phase is not None
        else obs.phase == PHASE_CHOICE and n_choice > 0
    )
    if is_choice and n_choice == 0:
        n_choice = int(rng.integers(2, CHOICE_OPTION_MAX + 1))

    if count is None:
        if is_choice:
            count = n_choice
        else:
            # 变长候选：多数 5~24 个，偶发 > CANDIDATE_MAX 触发截断分支
            count = 1 if rng.random() < 0.05 else int(rng.integers(1, 25))
            if rng.random() < 0.03:
                count = int(rng.integers(CANDIDATE_MAX + 1, max_count + 1))

    out: List[CandidateAction] = []
    for _ in range(count):
        if is_choice:
            out.append(CandidateAction(kind="choose", option=int(rng.integers(0, max(n_choice, 1)))))
            continue
        kind = _MOCK_KINDS[int(rng.integers(0, len(_MOCK_KINDS)))]
        cost = int(rng.integers(-1, 7))
        if kind == "buy" and n_tavern:
            out.append(CandidateAction(kind=kind, src_zone=ZONE_TAVERN,
                                       src_slot=int(rng.integers(0, n_tavern)), cost=cost))
        elif kind == "sell" and n_board:
            out.append(CandidateAction(kind=kind, src_zone=ZONE_BOARD,
                                       src_slot=int(rng.integers(0, n_board)), cost=cost))
        elif kind in ("play_minion", "play_spell") and n_hand:
            tgt_zone, tgt_slot = ZONE_NONE, -1
            if rng.random() < 0.4 and n_board:
                tgt_zone, tgt_slot = ZONE_BOARD, int(rng.integers(0, n_board))
            elif rng.random() < 0.2 and n_tavern:
                tgt_zone, tgt_slot = ZONE_TAVERN, int(rng.integers(0, n_tavern))
            out.append(CandidateAction(
                kind=kind,
                src_zone=ZONE_HAND,
                src_slot=int(rng.integers(0, n_hand)),
                tgt_zone=tgt_zone,
                tgt_slot=tgt_slot,
                position=int(rng.integers(-1, n_board + 1)),
                cost=cost,
            ))
        elif kind == "hero_power":
            tgt_zone, tgt_slot = ZONE_NONE, -1
            if rng.random() < 0.5 and n_board:
                tgt_zone, tgt_slot = ZONE_BOARD, int(rng.integers(0, n_board))
            out.append(CandidateAction(kind=kind, tgt_zone=tgt_zone, tgt_slot=tgt_slot, cost=cost))
        elif kind == "activate" and n_board:
            out.append(CandidateAction(kind=kind, src_zone=ZONE_BOARD,
                                       src_slot=int(rng.integers(0, n_board)), cost=cost))
        elif kind == "choose":
            if n_choice:
                out.append(CandidateAction(kind=kind, option=int(rng.integers(0, n_choice))))
            else:
                out.append(CandidateAction(kind="end_turn"))
        else:
            out.append(CandidateAction(kind=kind if kind not in (
                "buy", "sell", "play_minion", "play_spell", "activate") else "reroll",
                cost=cost))
    return tuple(out)


# ══════════════════════════════════════════════════════════════════════
# 完整观测
# ══════════════════════════════════════════════════════════════════════


def random_observation(
    rng: np.random.Generator,
    *,
    card_ids: Optional[Sequence[str]] = None,
    num_players: int = PLAYER_MAX,
    choice_prob: float = 0.12,
    turn: Optional[int] = None,
    include_hero: bool = True,
    candidate_count: Optional[int] = None,
) -> Observation:
    """生成一条随机但结构合法的 ``Observation``。"""
    turn = int(turn) if turn is not None else int(rng.integers(1, 16))
    is_choice = rng.random() < choice_prob
    board = random_entities(rng, ZONE_BOARD, BOARD_MAX, card_ids=card_ids)
    hand = random_entities(rng, ZONE_HAND, HAND_MAX, max_count=6, card_ids=card_ids)
    tavern = random_entities(rng, ZONE_TAVERN, TAVERN_MAX, card_ids=card_ids)
    trinkets = random_entities(rng, ZONE_TRINKET, TRINKET_MAX, card_ids=card_ids)
    quest = random_entity(rng, ZONE_QUEST, 0, card_ids=card_ids) if rng.random() < 0.25 else None
    opponent_board = random_entities(
        rng, ZONE_OPPONENT, OPPONENT_BOARD_MAX, card_ids=card_ids
    )
    lobby = random_lobby(rng, num_players)
    alive_count = sum(1 for p in lobby if p.alive)
    total_players = num_players

    pending: Optional[PendingChoice] = None
    if is_choice:
        n_opt = int(rng.integers(2, CHOICE_OPTION_MAX + 1))
        options = tuple(
            random_entity(rng, ZONE_CHOICE, i, card_ids=card_ids) for i in range(n_opt)
        )
        pending = PendingChoice(
            kind=str(rng.choice(["discover", "triple", "quest", "trinket", "dark_gift"])),
            options=options,
            for_agent=True,
            prompt="mock choice",
        )

    obs = Observation(
        version=1,
        turn=turn,
        phase=PHASE_CHOICE if pending is not None else PHASE_RECRUIT,
        hero=random_hero(rng, card_ids=card_ids) if include_hero else None,
        board=board,
        hand=hand,
        tavern=tavern,
        trinkets=trinkets,
        quest=quest,
        opponent_board=opponent_board,
        lobby=lobby,
        alive_count=alive_count,
        total_players=total_players,
        rank=int(rng.integers(1, max(alive_count, 1) + 1)),
        pending_choice=pending,
        candidates=(),
        log="",
    )
    cands = random_candidates(rng, obs, count=candidate_count)
    obs.candidates = cands
    return obs


# ══════════════════════════════════════════════════════════════════════
# 弱教师（BC 自测用：只看候选类型/费用的确定性偏好）
# ══════════════════════════════════════════════════════════════════════

#: 教师对动作类型的偏好（数值越大越优先；仅用于合成数据自测）
TEACHER_KIND_PREFERENCE = {
    "buy": 3.0,
    "play_minion": 2.6,
    "play_spell": 2.2,
    "upgrade": 1.8,
    "activate": 1.4,
    "choose": 2.4,
    "hero_power": 1.0,
    "reroll": 0.8,
    "sell": 0.6,
    "use_dark_gift": 0.5,
    "freeze": 0.3,
    "end_turn": 0.2,
}


def teacher_score(cand: CandidateAction) -> float:
    """弱教师打分：候选自身可见特征的线性函数（模型可学）。"""
    kind = getattr(cand.kind, "value", cand.kind)
    score = TEACHER_KIND_PREFERENCE.get(kind, 0.0)
    if cand.cost is not None and cand.cost >= 0:
        score += 0.05 * cand.cost
    if cand.position is not None and cand.position >= 0:
        score += 0.02 * cand.position
    return score


def teacher_choose(obs: Observation, rng: Optional[np.random.Generator] = None) -> int:
    """弱教师动作选择（并列随机，但用 rng 可复现）。"""
    n = len(obs.candidates)
    if n == 0:
        return 0
    scores = np.asarray([teacher_score(c) for c in obs.candidates], dtype=np.float64)
    if rng is not None:
        scores = scores + rng.random(n) * 1e-6
    return int(np.argmax(scores))
