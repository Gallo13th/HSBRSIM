"""换位去抖守卫（``CollectConfig.move_guard``）单测。

覆盖：
- 逆换位屏蔽 / 同动作上限 / 每回合 cap；
- 空掩码回退 EndTurn（计 ``move_guard_forced``）与「无 EndTurn 完全回退」；
- 多局（game_id）与多回合（turn）状态隔离；
- ``move_guard=False`` 与旧行为逐位等价：不改 mask、不新增 record/meta 字段、
  不扰动 RNG（掩码里没有 Move 时守卫开/关动作序列完全相同）；
- lockstep 采集 meta 里确实写入守卫统计（需要 hsbg_engine；引擎缺失时跳过）。
"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.move_guard import (MOVE_HI, MOVE_LO, MoveGuard,
                                      aggregate_move_guard, decode_move,
                                      encode_move, is_move)

N_ACTIONS = 245
END_TURN = 0
BUY0 = 8


def _mask(*actions: int) -> np.ndarray:
    m = np.zeros(N_ACTIONS, dtype=bool)
    for a in actions:
        m[int(a)] = True
    return m


# ── 纯规则层 ─────────────────────────────────────────────────────────────
def test_move_encoding():
    assert (MOVE_LO, MOVE_HI) == (196, 245)
    assert is_move(196) and is_move(244) and not is_move(195) and not is_move(245)
    assert encode_move(0, 1) == 197
    assert encode_move(1, 0) == 203
    assert encode_move(0, 0) == 196
    assert decode_move(203) == (1, 0)
    with pytest.raises(ValueError):
        decode_move(0)
    with pytest.raises(ValueError):
        encode_move(7, 0)


def test_inverse_blocked():
    g = MoveGuard(cap=99, repeat_limit=99)
    m = _mask(END_TURN, encode_move(0, 1), encode_move(1, 0), encode_move(0, 2))
    out, forced = g.guarded_mask(m, game_id=1, seat=0, turn=1)
    assert not forced
    assert list(out) == list(m)                     # 还没走过任何换位 -> 全放行
    g.note_action(encode_move(0, 1), game_id=1, seat=0, turn=1)
    out, forced = g.guarded_mask(m, game_id=1, seat=0, turn=1)
    assert not forced
    assert not out[encode_move(1, 0)]               # 逆换位（撤销）被屏蔽
    assert out[encode_move(0, 1)] and out[encode_move(0, 2)]
    assert g.stats.blocked_inverse == 1


def test_inverse_only_applies_to_immediately_previous_move():
    g = MoveGuard(cap=99, repeat_limit=99)
    g.note_action(encode_move(0, 1), game_id=1, seat=0, turn=1)
    g.note_action(BUY0, game_id=1, seat=0, turn=1)   # 上一步不是换位
    m = _mask(END_TURN, encode_move(1, 0))
    out, _ = g.guarded_mask(m, game_id=1, seat=0, turn=1)
    assert out[encode_move(1, 0)]                    # 不再屏蔽逆换位


def test_repeat_limit():
    g = MoveGuard(cap=99, repeat_limit=2)
    mv = encode_move(3, 4)
    m = _mask(END_TURN, mv, BUY0)
    for i in range(2):
        out, forced = g.guarded_mask(m, game_id=1, seat=0, turn=1)
        assert out[mv] and not forced
        g.note_action(mv, game_id=1, seat=0, turn=1)
    out, forced = g.guarded_mask(m, game_id=1, seat=0, turn=1)
    assert not out[mv]                               # 第 3 次被屏蔽
    assert out[END_TURN] and out[BUY0] and not forced
    assert g.stats.blocked_repeat >= 1
    assert g.stats.moves == 2


def test_cap_blocks_all_moves():
    g = MoveGuard(cap=3, repeat_limit=99)
    m = _mask(END_TURN, BUY0, encode_move(0, 1), encode_move(2, 3), encode_move(5, 6))
    for a in (encode_move(0, 1), encode_move(2, 3), encode_move(5, 6)):
        g.note_action(a, game_id=1, seat=0, turn=1)
    out, forced = g.guarded_mask(m, game_id=1, seat=0, turn=1)
    assert not forced
    assert not out[MOVE_LO:MOVE_HI].any()            # 全部换位被屏蔽
    assert out[END_TURN] and out[BUY0]
    assert g.stats.blocked_cap == 3


def test_empty_mask_falls_back_to_end_turn():
    # 只剩 EndTurn：守卫等价于强制结束本回合 -> forced 计数
    g = MoveGuard(cap=1, repeat_limit=2)
    mv = encode_move(0, 1)
    g.note_action(mv, game_id=1, seat=0, turn=1)     # 已达 cap=1
    out, forced = g.guarded_mask(_mask(END_TURN, mv), game_id=1, seat=0, turn=1)
    assert forced and out[END_TURN] and int(out.sum()) == 1
    assert g.stats.forced == 1
    assert g.stats.blocked_cap == 1
    # 只要有非 EndTurn 的替代动作就不 forced
    out, forced = g.guarded_mask(_mask(END_TURN, BUY0, mv), game_id=1, seat=0, turn=1)
    assert not forced and out[END_TURN] and out[BUY0] and not out[mv]


def test_empty_mask_without_end_turn_reverts():
    g = MoveGuard(cap=0, repeat_limit=2)
    m = _mask(encode_move(0, 1))                     # EndTurn 不在 mask 里
    out, forced = g.guarded_mask(m, game_id=1, seat=0, turn=1)
    assert not forced and list(out) == list(m)       # 完全回退原 mask，不计数
    assert g.stats.blocked_cap == 0 and g.stats.forced == 0


def test_game_and_turn_isolation():
    g = MoveGuard(cap=99, repeat_limit=2)
    mv = encode_move(1, 2)
    m = _mask(END_TURN, mv)
    # game 1: 两次同动作
    for _ in range(2):
        g.note_action(mv, game_id=1, seat=0, turn=1)
    out, _ = g.guarded_mask(m, game_id=1, seat=0, turn=1)
    assert not out[mv]                               # game1 超限
    out, _ = g.guarded_mask(m, game_id=2, seat=0, turn=1)
    assert out[mv]                                   # game2 独立计数
    out, _ = g.guarded_mask(m, game_id=1, seat=0, turn=2)
    assert out[mv]                                   # 新回合重置
    out, _ = g.guarded_mask(m, game_id=1, seat=1, turn=1)
    assert out[mv]                                   # 不同座位独立


def test_stats_meta_and_aggregate():
    g = MoveGuard(cap=3, repeat_limit=2)
    g.note_action(encode_move(0, 1), game_id=1, seat=0, turn=1)
    g.guarded_mask(_mask(END_TURN, encode_move(1, 0)), game_id=1, seat=0, turn=1)
    meta = g.to_meta()
    assert meta["move_guard"] is True
    for key in ("move_guard_blocked_inverse", "move_guard_blocked_repeat",
                "move_guard_blocked_cap", "move_guard_forced",
                "move_guard_decisions", "move_guard_moves", "move_cap",
                "move_repeat_limit"):
        assert key in meta
    assert meta["move_guard_blocked_inverse"] == 1
    assert aggregate_move_guard([]) == {}
    assert aggregate_move_guard([{}, {"move_guard": False}]) == {}
    two = aggregate_move_guard([meta, meta])
    assert two["move_guard"] and two["move_guard_blocked_inverse"] == 2
    assert two["move_cap"] == 3


def test_invalid_params():
    with pytest.raises(ValueError):
        MoveGuard(cap=-1)
    with pytest.raises(ValueError):
        MoveGuard(repeat_limit=0)


# ── policy 层（stub evaluator，无需模型前向）─────────────────────────────
class _DummyModel:
    def eval(self):
        return self

    def to(self, device):
        return self


class _LastLegalEval:
    """确定性 stub：优先「最后一个合法 Move」，否则 Play > Buy > EndTurn > 最后合法。

    这样构造出一个稳定的「换位刷子」（同时会把随从铺到棋盘上，让换位真的合法），
    用来验证守卫在真实引擎上的去抖效果。
    """

    name = "stub"

    @staticmethod
    def _pick(mask):
        legal = np.flatnonzero(np.asarray(mask, dtype=bool))
        if not legal.size:
            return 0
        blocks = ((MOVE_LO, MOVE_HI), (46, 126), (8, 16))
        for lo, hi in blocks:
            sel = legal[(legal >= lo) & (legal < hi)]
            if sel.size:
                return int(sel[-1])
        return 0 if bool(mask[0]) else int(legal[-1])

    def act(self, features, cards, mask, temperature=1.0, seed=None):
        return self._pick(mask), 0.0, 0.0

    def act_batch(self, features, cards, mask, temperature=1.0, seed=None):
        m2 = np.atleast_2d(np.asarray(mask, dtype=bool))
        acts = np.asarray([self._pick(m) for m in m2], dtype=np.int64)
        return (acts, np.zeros(len(acts), np.float32),
                np.zeros(len(acts), np.float32))


class _FakeGame:
    """只提供 policy 需要的 observe/legal_mask/turn。"""

    def __init__(self, mask, turn=1):
        self._mask = np.asarray(mask, dtype=bool)
        self.turn = int(turn)

    def observe(self, seat):
        return (np.zeros(3227, np.float32).tobytes(),
                np.zeros(124, np.int32).tobytes())

    def legal_mask(self, seat):
        return self._mask.astype(np.uint8).tobytes()


def _make_policy(**cfg_kw):
    pytest.importorskip("torch")          # policy 构造需要 torch
    from hsbg.az.train.ppo import CollectConfig, PPOSelfPlayPolicy
    cfg = CollectConfig(behavior="net", fast_act=True, temperature=1.0,
                        max_actions_per_turn=40, **cfg_kw)
    return PPOSelfPlayPolicy(_DummyModel(), device="cpu", config=cfg,
                             eval_fn=_LastLegalEval(), seed=1234,
                             move_model=False)


def test_policy_guard_off_is_bitwise_legacy():
    mask = _mask(END_TURN, BUY0, 46, encode_move(0, 1), encode_move(1, 0))
    game = _FakeGame(mask)
    p_off = _make_policy(move_guard=False)
    p_off2 = _make_policy(move_guard=False)
    assert p_off._guard is None and p_off.move_guard_meta() == {}
    seq_a, seq_b = [], []
    for _ in range(6):
        d1 = p_off.decide(game, 0)
        d2 = p_off2.decide(game, 0)
        seq_a.append((int(d1.action), float(d1.info["logprob"])))
        seq_b.append((int(d2.action), float(d2.info["logprob"])))
    assert seq_a == seq_b                           # 同 seed 可复现
    # 记录里不出现守卫字段、mask 就是引擎 mask 的逐位拷贝
    legacy = {"features", "cards", "mask", "action", "old_logprob", "value",
              "target_pi", "seat", "turn", "game_id", "forced"}
    assert set(p_off.records[0].keys()) == legacy
    for rec in p_off.records:
        assert np.array_equal(np.asarray(rec["mask"]), mask)
        assert 196 <= int(rec["action"]) < 245        # stub 取最后一个合法动作


def test_policy_guard_on_no_move_mask_is_bitwise_equal_to_off():
    """mask 里没有 Move 时守卫不清任何位：动作/概率与关闭时逐位相同。"""
    mask = _mask(END_TURN, BUY0, 46, 16)
    game = _FakeGame(mask)
    p_off = _make_policy(move_guard=False)
    p_on = _make_policy(move_guard=True, move_cap=3, move_repeat_limit=2)
    for _ in range(8):
        d_off = p_off.decide(game, 0)
        d_on = p_on.decide(game, 0)
        assert int(d_off.action) == int(d_on.action)
        assert float(d_off.info["logprob"]) == float(d_on.info["logprob"])
    assert p_on.move_guard_meta()["move_guard_blocked_inverse"] == 0
    assert p_on.move_guard_meta()["move_guard_blocked_repeat"] == 0
    assert p_on.move_guard_meta()["move_guard_blocked_cap"] == 0
    assert p_on.move_guard_meta()["move_guard_moves"] == 0


def test_policy_guard_inverse_and_repeat():
    mv_in = encode_move(0, 1)
    mv_out = encode_move(1, 0)
    mask = _mask(END_TURN, BUY0, mv_in, mv_out)
    game = _FakeGame(mask)
    p = _make_policy(move_guard=True, move_cap=99, move_repeat_limit=2)
    a1 = int(p.decide(game, 0).action)
    assert a1 == mv_out                              # 第一次：最后一个合法动作
    a2 = int(p.decide(game, 0).action)
    assert a2 == mv_out                              # 第二次：同动作仍允许（limit=2）
    a3 = int(p.decide(game, 0).action)
    assert a3 == BUY0                                # 逆换位 + 重复超限 -> 屏蔽 Move
    meta = p.move_guard_meta()
    assert meta["move_guard_moves"] == 2
    assert meta["move_guard_blocked_inverse"] == 2   # 两次决策各屏蔽一个逆动作位
    assert meta["move_guard_blocked_repeat"] == 1
    # 记录里的 mask 是守卫后的 mask（on-policy：动作在其内、被禁位为 0）
    rec = p.records[-1]
    assert not np.asarray(rec["mask"])[mv_in] and not np.asarray(rec["mask"])[mv_out]
    assert np.asarray(rec["mask"])[int(rec["action"])]


def test_policy_guard_cap_and_forced_fallback():
    mvs = [encode_move(0, 1), encode_move(1, 2), encode_move(2, 3)]
    mask = _mask(END_TURN, *mvs)
    game = _FakeGame(mask)
    p = _make_policy(move_guard=True, move_cap=1, move_repeat_limit=99)
    assert int(p.decide(game, 0).action) == mvs[-1]
    d2 = p.decide(game, 0)
    assert int(d2.action) == END_TURN                 # cap 后只剩 EndTurn -> 回退
    assert bool(d2.info["forced"]) and float(d2.info["logprob"]) == 0.0
    assert int(p.forced_actions) == 0                 # 守卫回退不计入回合数守卫
    meta = p.move_guard_meta()
    assert meta["move_guard_forced"] == 1
    assert meta["move_guard_blocked_cap"] == 3


def test_policy_guard_multi_game_isolation():
    mv = encode_move(0, 1)
    mask = _mask(END_TURN, BUY0, mv)
    game = _FakeGame(mask)
    p = _make_policy(move_guard=True, move_cap=99, move_repeat_limit=2)
    p.game_id = 1
    assert int(p.decide(game, 0).action) == mv
    assert int(p.decide(game, 0).action) == mv
    p.game_id = 2
    assert int(p.decide(game, 0).action) == mv        # 新 game 独立计数（第 1 次）
    p.game_id = 1
    assert int(p.decide(game, 0).action) == BUY0      # game1 已两次 -> 屏蔽
    p.game_id = 2
    assert int(p.decide(game, 0).action) == mv        # game2 第 2 次仍允许
    assert int(p.decide(game, 0).action) == BUY0      # game2 第 3 次 -> 屏蔽
    p.reset()                                         # 每局 reset 清回合历史
    assert int(p.decide(game, 0).action) == mv


def test_lockstep_meta_has_guard_stats():
    pytest.importorskip("hsbg_engine")
    pytest.importorskip("torch")
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep
    from hsbg.az.train.ppo import CollectConfig

    cfg = CollectConfig(games=1, seed=7, opponent="bot", behavior="net",
                        max_steps=20000, max_actions_per_turn=40,
                        move_guard=True, move_cap=2, move_repeat_limit=2)
    records, meta = collect_ppo_lockstep(
        _DummyModel(), cfg, eval_fn=_LastLegalEval(), device="cpu",
        seed=7, games=1, gamemode="bot", engine_backend="auto")
    assert records, "应当采到决策"
    assert meta["move_guard"] is True
    assert meta["move_cap"] == 2
    assert meta["move_guard_decisions"] >= len(records) - 2   # 近乎每决策一次
    assert meta["move_guard_moves"] > 0
    assert meta["move_guard_blocked_inverse"] + \
        meta["move_guard_blocked_repeat"] + meta["move_guard_blocked_cap"] > 0
    # 每回合换位数 <= cap（守卫在采集路径真的生效）
    per_turn = {}
    for r in records:
        key = (int(r["game_id"]), int(r["turn"]))
        if MOVE_LO <= int(r["action"]) < MOVE_HI:
            per_turn[key] = per_turn.get(key, 0) + 1
    assert per_turn and max(per_turn.values()) <= 2
    # 逆换位从不在「上一步是换位」后出现
    prev = {}
    for r in records:
        key = (int(r["game_id"]), int(r["seat"]))
        a = int(r["action"])
        if key in prev:
            pa, pturn = prev[key]
            if pturn == int(r["turn"]) and pa >= MOVE_LO and pa < MOVE_HI:
                src, dst = decode_move(pa)
                assert a != encode_move(dst, src)
        prev[key] = (a, int(r["turn"]))
    # 关闭守卫时 meta 不出现任何 guard 键（默认关闭零影响）
    cfg_off = CollectConfig(games=1, seed=7, opponent="bot", behavior="net",
                            max_steps=20000, max_actions_per_turn=40)
    _, meta_off = collect_ppo_lockstep(
        _DummyModel(), cfg_off, eval_fn=_LastLegalEval(), device="cpu",
        seed=7, games=1, gamemode="bot", engine_backend="auto")
    assert not any(k.startswith("move_guard") or k in ("move_cap",
                                                       "move_repeat_limit")
                   for k in meta_off)
