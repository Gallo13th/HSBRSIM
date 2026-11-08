"""竞技场部署路径（``scripts/arena_agent.act``）的换位去抖守卫单测。

覆盖（对应 docs/ARENA_GUARD.md）：

1. 逆换位被屏蔽；
2. 同一 ``(from,to)`` 超过 repeat_limit 被屏蔽；
3. 每回合 cap 生效（屏蔽全部换位）；
4. 新回合重置（context.turn 变化；无 context.turn 时退回观测指纹）；
5. 守卫清空全部合法动作 -> 回退 EndTurn 且 ``forced`` +1；
6. ``ARENA_MOVE_GUARD=0`` 与旧行为（纯 masked argmax）逐位一致，且不新增
   状态/日志字段；
7. 环境变量默认值（默认开、cap=3、repeat=2）与非法值兜底。

测试用**固定 logits 的 stub 前向**（monkeypatch ``ppo.forward_model``），不加载
checkpoint、不依赖 GPU / 引擎；只验证 ``act`` 的掩码改写与回合状态机。
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.arena_agent as AA  # noqa: E402
from hsbg.az.train.move_guard import (DEFAULT_MOVE_CAP,  # noqa: E402
                                      DEFAULT_MOVE_REPEAT_LIMIT, MoveGuard,
                                      encode_move)
from hsbg.env.obs_std import SLICE_CARD_BOARD, SLICE_CARD_HAND, SLICE_CARD_SHOP  # noqa: E402

N_ACTIONS = 245
END_TURN = 0
MV_01 = encode_move(0, 1)      # 197
MV_10 = encode_move(1, 0)      # 203
MV_02 = encode_move(0, 2)      # 198
MV_23 = encode_move(2, 3)      # 226

#: stub 前向的 logits（测试逐决策改写）
_LOGITS = {"v": np.zeros(N_ACTIONS, dtype=np.float32)}


def _set_logits(overrides: dict) -> None:
    v = np.zeros(N_ACTIONS, dtype=np.float32)
    for idx, val in overrides.items():
        v[int(idx)] = float(val)
    _LOGITS["v"] = v


@pytest.fixture()
def arena(monkeypatch):
    """把 ``arena_agent`` 换成 stub 模型，默认环境（守卫开、cap=3、repeat=2）。"""
    torch = pytest.importorskip("torch")
    import hsbg.az.train.ppo as ppo

    fresh = {"model": object(), "torch": torch, "device": "cpu", "map": None,
             "ckpt": "<stub>", "norm_mean": None, "norm_std": None,
             "action_log": "", "counters": None, "guard": None,
             "guard_cfg": None, "turn_state": {}}
    monkeypatch.setattr(AA, "_state", fresh)
    monkeypatch.setattr(AA, "_load", lambda: None)
    for name in ("ARENA_MOVE_GUARD", "ARENA_MOVE_CAP", "ARENA_MOVE_REPEAT_LIMIT",
                 "ARENA_ACTION_LOG"):
        monkeypatch.delenv(name, raising=False)

    def _forward(model, x, c, m=None):  # noqa: ANN001 - 与 forward_model 同签名
        return (torch.tensor(_LOGITS["v"], dtype=torch.float32).reshape(1, -1), None)

    monkeypatch.setattr(ppo, "forward_model", _forward)
    return AA


def _observation(actions, *, turn=1, board=(101, 102), shop=(201, 202),
                 hand=(301,)) -> dict:
    """构造一份 v1 形状的竞技场观测（features/cards/mask 都取本地口径）。"""
    features = np.zeros(AA.OBS_FLOATS, dtype=np.float32)
    features[0] = float(turn) / 20.0                 # global.turn
    cards = np.zeros(AA.OBS_CARDS, dtype=np.int64)
    board = list(board)[:7]
    cards[SLICE_CARD_BOARD] = board + [0] * (7 - len(board))
    shop = list(shop)[:8]
    cards[SLICE_CARD_SHOP] = shop + [0] * (8 - len(shop))
    hand = list(hand)[:10]
    cards[SLICE_CARD_HAND] = hand + [0] * (10 - len(hand))
    mask = np.zeros(N_ACTIONS, dtype=np.uint8)
    for a in actions:
        mask[int(a)] = 1
    return {"features": features, "cards": cards, "action_mask": mask}


def _run(actions, *, turn=1, seat=0, match=1, ctx_turn=True, board=(101, 102),
         shop=(201, 202)) -> int:
    ctx = {"match_id": match, "seat": seat}
    if ctx_turn:
        ctx["turn"] = int(turn)
    return int(AA.act(_observation(actions, turn=turn, board=board, shop=shop), ctx))


def _legacy_action(mask, logits) -> int:
    """旧路径（守卫关闭）逐位等价实现：masked argmax + 兜底第一个合法动作。"""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return 0
    x = np.where(m, np.asarray(logits, dtype=np.float64), -np.inf)
    a = int(np.argmax(x))
    if not m[a]:
        nz = np.flatnonzero(m)
        a = int(nz[0]) if nz.size else 0
    return a


# ── 规则 1：逆换位 ────────────────────────────────────────────────────────
def test_inverse_move_is_blocked(arena):
    actions = [END_TURN, MV_01, MV_10]
    _set_logits({MV_10: 12.0, END_TURN: 0.5})
    assert _run(actions) == MV_10                    # 第一次：正常选中
    # 上一步是 (1,0)；逆换位 (0,1) 必须被屏蔽（哪怕 logits 偏爱它）
    _set_logits({MV_01: 12.0, END_TURN: -1.0})
    got = _run(actions)
    assert got != MV_01
    assert got == MV_10
    meta = AA.guard_meta()
    assert meta["move_guard_blocked_inverse"] >= 1
    assert meta["move_guard_moves"] == 2


def test_inverse_only_after_immediately_previous_move(arena):
    actions = [END_TURN, MV_01, MV_10]
    _set_logits({MV_10: 12.0, END_TURN: 5.0})
    assert _run(actions) == MV_10                    # move (1,0)
    _set_logits({END_TURN: 12.0})                    # 中间插一个 EndTurn
    assert _run(actions) == END_TURN
    _set_logits({MV_01: 12.0, END_TURN: 5.0})        # 再选 (0,1) 不再算逆换位
    assert _run(actions) == MV_01


# ── 规则 2：同一 (from,to) 重复上限 ──────────────────────────────────────
def test_repeat_limit_blocks_third(arena):
    actions = [END_TURN, MV_01]
    _set_logits({MV_01: 10.0, END_TURN: 0.2})
    assert _run(actions) == MV_01
    assert _run(actions) == MV_01                    # repeat_limit=2：第 2 次仍放行
    assert _run(actions) == END_TURN                 # 第 3 次被屏蔽
    meta = AA.guard_meta()
    assert meta["move_guard_blocked_repeat"] >= 1
    assert meta["move_guard_moves"] == 2
    assert meta["move_repeat_limit"] == DEFAULT_MOVE_REPEAT_LIMIT == 2


# ── 规则 3：每回合 cap ───────────────────────────────────────────────────
def test_cap_blocks_all_moves(arena, monkeypatch):
    monkeypatch.setenv("ARENA_MOVE_CAP", "1")
    actions = [END_TURN, MV_01, MV_10, MV_02, MV_23]
    _set_logits({MV_01: 10.0, END_TURN: 0.5})
    assert _run(actions) == MV_01                    # 用满 cap=1
    _set_logits({MV_23: 10.0, END_TURN: 0.5})        # 全部换位应被屏蔽
    assert _run(actions) == END_TURN
    meta = AA.guard_meta()
    assert meta["move_cap"] == 1
    assert meta["move_guard_blocked_cap"] >= 4
    assert meta["move_guard_forced"] == 1


# ── 规则 4：新回合重置 ───────────────────────────────────────────────────
def test_new_turn_resets_state(arena):
    actions = [END_TURN, MV_01]
    _set_logits({MV_01: 10.0, END_TURN: 0.2})
    for _ in range(2):
        assert _run(actions, turn=1) == MV_01
    assert _run(actions, turn=1) == END_TURN         # 回合 1 已超 repeat
    assert _run(actions, turn=2) == MV_01            # turn 变化 -> 重置
    assert AA.guard_meta()["move_guard_moves"] == 3


def test_signature_fallback_when_context_lacks_turn(arena):
    """没有 context.turn 时用观测指纹（turn 标量）判断新回合。"""
    actions = [END_TURN, MV_01]
    _set_logits({MV_01: 10.0, END_TURN: 0.2})
    for _ in range(2):
        assert _run(actions, turn=1, ctx_turn=False) == MV_01
    assert _run(actions, turn=1, ctx_turn=False) == END_TURN
    assert _run(actions, turn=2, ctx_turn=False) == MV_01


def test_context_turn_wins_over_midturn_signature(arena):
    """有 context.turn 时，回合内买牌（酒馆多重集变化）不得重置守卫。"""
    actions = [END_TURN, MV_01]
    _set_logits({MV_01: 10.0, END_TURN: 0.2})
    for _ in range(2):
        assert _run(actions, turn=3, shop=(201, 202)) == MV_01
    # 同一回合内酒馆换了（买牌）：不能当成新回合
    assert _run(actions, turn=3, shop=(201, 203)) == END_TURN
    assert _run(actions, turn=4) == MV_01


def test_seats_and_matches_are_isolated(arena):
    actions = [END_TURN, MV_01]
    _set_logits({MV_01: 10.0, END_TURN: 0.2})
    for _ in range(2):
        _run(actions, turn=1, seat=0, match=1)
    assert _run(actions, turn=1, seat=0, match=1) == END_TURN
    assert _run(actions, turn=1, seat=0, match=2) == MV_01           # 另一局
    assert _run(actions, turn=1, seat=1, match=1) == MV_01           # 另一座位
    AA.reset_state()                                                 # 换局显式清状态
    assert _run(actions, turn=1, seat=0, match=1) == MV_01


# ── 规则 5：空掩码回退 EndTurn ───────────────────────────────────────────
def test_empty_guard_mask_falls_back_to_end_turn(arena, monkeypatch):
    monkeypatch.setenv("ARENA_MOVE_CAP", "0")
    _set_logits({MV_01: 10.0, END_TURN: 0.5})
    assert _run([END_TURN, MV_01]) == END_TURN
    meta = AA.guard_meta()
    assert meta["move_guard_forced"] == 1
    assert AA._stats()["move_guard_forced"] == 1
    # 没有 EndTurn 合法时完全回退原 mask（不 forced、不丢动作）
    _set_logits({MV_01: 10.0})
    assert _run([MV_01]) == MV_01


# ── 规则 6：关闭时与旧行为逐位一致 ───────────────────────────────────────
def test_guard_off_is_bitwise_legacy(arena, monkeypatch):
    monkeypatch.setenv("ARENA_MOVE_GUARD", "0")
    seq = [
        ([END_TURN, MV_01, MV_10], {MV_10: 9.0, END_TURN: 0.4}, 1),
        ([END_TURN, MV_01, MV_10], {MV_01: 9.0, END_TURN: 0.4}, 1),
        ([END_TURN, MV_01, MV_10], {MV_01: 9.0, END_TURN: 0.4}, 1),
        ([END_TURN, MV_01], {MV_01: -1.0, END_TURN: 2.0}, 1),
        ([END_TURN, MV_02], {MV_02: 9.0}, 2),
        ([END_TURN, MV_02], {MV_02: 9.0, END_TURN: 3.0}, 2),
    ]
    for actions, logits, turn in seq:
        _set_logits(logits)
        got = int(AA.act(_observation(actions, turn=turn),
                         {"match_id": 9, "seat": 0, "turn": turn}))
        mask = np.zeros(N_ACTIONS, dtype=bool)
        mask[actions] = True
        assert got == _legacy_action(mask, _LOGITS["v"])
    assert AA.guard_meta() == {}                     # 不新增守卫统计
    assert AA._state["turn_state"] == {}             # 不建回合状态
    assert "move_guard" not in AA._stats()           # 计数器也不新增键


def test_guard_off_action_log_keeps_legacy_fields(arena, monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_MOVE_GUARD", "0")
    log = tmp_path / "act.jsonl"
    AA._state["action_log"] = str(log)
    _set_logits({MV_01: 5.0, END_TURN: 1.0})
    AA.act(_observation([END_TURN, MV_01], turn=1),
           {"match_id": 1, "seat": 0, "turn": 1})
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    legacy = {"match_id", "seat", "turn", "actions_used", "action", "segment",
              "mask_legal", "move_legal_bits", "counter"}
    assert set(rec) == legacy


def test_guard_on_action_log_records_trigger(arena, monkeypatch, tmp_path):
    log = tmp_path / "act.jsonl"
    AA._state["action_log"] = str(log)
    _set_logits({MV_01: 5.0, END_TURN: 1.0})
    AA.act(_observation([END_TURN, MV_01], turn=1),
           {"match_id": 1, "seat": 0, "turn": 1})
    AA.act(_observation([END_TURN, MV_01], turn=1),
           {"match_id": 1, "seat": 0, "turn": 1})
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["move_guard"] is True
    assert rows[-1]["guard_forced"] is False
    assert rows[-1]["moves_this_turn"] == 2
    assert rows[-1]["move_cap"] == DEFAULT_MOVE_CAP == 3


# ── 规则 7：默认值 / 环境变量 ────────────────────────────────────────────
def test_defaults_guard_enabled(arena):
    cfg = AA._guard_cfg()
    assert cfg == {"enabled": True, "cap": DEFAULT_MOVE_CAP,
                   "repeat_limit": DEFAULT_MOVE_REPEAT_LIMIT}
    assert AA._guard() is not None
    assert AA.guard_meta()["move_guard"] is True


def test_env_parsing_and_invalid_fallback(arena, monkeypatch):
    monkeypatch.setenv("ARENA_MOVE_GUARD", "0")
    assert AA._guard_cfg()["enabled"] is False
    assert AA._guard() is None
    monkeypatch.setenv("ARENA_MOVE_GUARD", "1")
    monkeypatch.setenv("ARENA_MOVE_CAP", "4")
    monkeypatch.setenv("ARENA_MOVE_REPEAT_LIMIT", "1")
    cfg = AA._guard_cfg()
    assert (cfg["enabled"], cfg["cap"], cfg["repeat_limit"]) == (True, 4, 1)
    monkeypatch.setenv("ARENA_MOVE_CAP", "not-a-number")
    monkeypatch.setenv("ARENA_MOVE_REPEAT_LIMIT", "")
    cfg = AA._guard_cfg()
    assert cfg["cap"] == DEFAULT_MOVE_CAP and cfg["repeat_limit"] == DEFAULT_MOVE_REPEAT_LIMIT
    # 越界值同样退回训练默认（不能把对局搞崩）
    monkeypatch.setenv("ARENA_MOVE_CAP", "-1")
    monkeypatch.setenv("ARENA_MOVE_REPEAT_LIMIT", "0")
    cfg = AA._guard_cfg()
    assert cfg["cap"] == DEFAULT_MOVE_CAP and cfg["repeat_limit"] == DEFAULT_MOVE_REPEAT_LIMIT
    # 配置变化会重建守卫（保证换配置后是干净状态）
    g1 = AA._guard()
    monkeypatch.setenv("ARENA_MOVE_CAP", "2")
    g2 = AA._guard()
    assert g2 is not g1 and g2.cap == 2


def test_guard_uses_training_move_guard_rules(arena):
    """部署侧就是训练侧那个类：同配置、同规则实现（不是另写一份）。"""
    g = AA._guard()
    assert isinstance(g, MoveGuard)
    ref = MoveGuard(cap=DEFAULT_MOVE_CAP, repeat_limit=DEFAULT_MOVE_REPEAT_LIMIT)
    mask = np.zeros(N_ACTIONS, dtype=bool)
    mask[[END_TURN, MV_01, MV_10]] = True
    got, forced = g.guarded_mask(mask, game_id=1, seat=0, turn=0)
    exp, exp_forced = ref.guarded_mask(mask, game_id=1, seat=0, turn=0)
    assert np.array_equal(got, exp) and forced == exp_forced
