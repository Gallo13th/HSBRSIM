"""换位动作（Move / reposition，196..244）全链路回归。

覆盖 docs/POSITION_ACTION_AUDIT.md 的四条链路，任何一层把换位静默掩掉都会失败：

1. 动作空间：``hsbg.env.action_space_std`` 的 Move 段编码 = ``196 + from*7 + to``；
2. 引擎：``Game.legal_mask`` 在 ≥2 随从时置位 ``n*(n-1)`` 个换位位、``Game.step`` 接受并
   真正改变棋盘顺序、``from == to`` 被拒绝；
3. 训练侧采样：``PPOSelfPlayPolicy.decide`` 在合法掩码上按行为分布采样，**不会**过滤换位
   （用把全部概率压在某个换位动作上的 stub evaluator 验证）；
4. 竞技场适配：``scripts.arena_agent.act`` 把模型输出的 0..244 索引**原样**透传，且我们的
   245 动作名列表与 TavernArena manifest 声明的 ``action_layout_sha256`` 逐字节一致
   （manifest 于 2026-10-30 取自 https://rizling.top/api/v1/manifest，
   ruleset ``tg36-bc45cfc55a0e5cd6c14c``）。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from hsbg.env import action_space_std as A

MOVE_LO, MOVE_HI = A.A_MOVE, A.A_MOVE + A.N_BOARD * A.N_BOARD  # 196..245

#: TavernArena 公开 manifest 的 ``action_layout_sha256``（245 个动作名序列的 sha256）。
#: 等价于 ``json.dumps([action_name(i) for i in 0..244], sort_keys=True,
#: separators=(',', ':')).encode()``。
ARENA_ACTION_LAYOUT_SHA256 = (
    "be2e97586b88025ead313ce26dc24fc5817c46cd3bf731662a92d34876e674bd")


def _mask(game, seat: int = 0) -> np.ndarray:
    return np.frombuffer(game.legal_mask(int(seat)), dtype=np.uint8).astype(bool)


def _board_card_ids(game, seat: int = 0):
    return [str(m.get("card")) for m in (json.loads(game.player_json(seat)).get("board") or [])]


def _fresh_recruit_game(seed: int = 7, turn: int = 2):
    """跑到 ``turn`` 的招募阶段并解掉 pending choice（换位只有在常规招募阶段合法）。"""
    engine = pytest.importorskip("hsbg_engine")
    game = engine.Game(seed=int(seed))
    steps = 0
    while not game.is_over() and int(game.turn) < int(turn) and steps < 5000:
        acted = False
        for p in range(int(game.num_players)):
            if game.is_over() or int(game.turn) >= int(turn):
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            game.step(p, int(game.bot_action(p)))
        if not acted:
            break
    # pending（Discover/ChooseOne/Target）下 legal_mask 只有 Choose/Cancel，先解掉
    for _ in range(32):
        if not game.needs_action(0):
            break
        mask = _mask(game, 0)
        if mask[MOVE_LO:MOVE_HI].any():
            break
        choose = np.flatnonzero(mask[A.A_CHOOSE:A.A_CHOOSE + A.N_CHOICE])
        if not choose.size:
            break
        game.step(0, int(A.A_CHOOSE + choose[0]))
    return game


# ── 1. 动作空间 ────────────────────────────────────────────────────────────
def test_move_segment_is_frozen_in_action_space():
    assert (A.A_MOVE, A.N_BOARD, A.N_ACTIONS) == (196, 7, 245)
    seg = [s for s in A.SEGMENTS if s[0] == "move"]
    assert len(seg) == 1
    name, lo, hi, count, _desc = seg[0]
    assert (name, lo, hi, count) == ("move", 196, 245, 49)
    # 编码 = 196 + from*7 + to，覆盖 49 个组合
    assert A.encode(A.Move(src=0, to=0)) == 196
    assert A.encode(A.Move(src=0, to=1)) == 197
    assert A.encode(A.Move(src=1, to=0)) == 203
    assert A.encode(A.Move(src=6, to=6)) == 244
    for src in range(A.N_BOARD):
        for dst in range(A.N_BOARD):
            idx = A.encode(A.Move(src=src, to=dst))
            assert MOVE_LO <= idx < MOVE_HI
            assert A.decode(idx) == A.Move(src=src, to=dst)
    assert {A.encode(A.Move(src=s, to=d)) for s in range(7) for d in range(7)} == \
        set(range(196, 245))


def test_move_names_match_engine_and_arena_layout_hash():
    engine = pytest.importorskip("hsbg_engine")
    ours = [engine.action_name(i) for i in range(245)]
    assert ours[196] == "Move { from: 0, to: 0 }"
    assert ours[197] == "Move { from: 0, to: 1 }"
    assert ours[244] == "Move { from: 6, to: 6 }"
    assert ours[196:245] == [A.action_name(i) for i in range(196, 245)]
    canonical = json.dumps(ours, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()
    assert hashlib.sha256(canonical).hexdigest() == ARENA_ACTION_LAYOUT_SHA256


# ── 2. 引擎：置位 + step 接受 + 顺序变化 ───────────────────────────────────
def test_engine_masks_accepts_and_applies_move():
    game = _fresh_recruit_game(seed=7, turn=2)
    applied = game.inject_board(0, [[1, 2, 2], [2, 3, 3], [3, 1, 1]], 4)
    assert applied.get("applied") is True, applied
    board = json.loads(game.player_json(0))["board"]
    assert len(board) == 3
    mask = _mask(game, 0)
    assert int(mask[MOVE_LO:MOVE_HI].sum()) == 3 * 2  # n*(n-1)：不含 from==to
    for k in range(7):
        assert not mask[A.encode(A.Move(src=k, to=k))]
    rel = np.flatnonzero(mask[MOVE_LO:MOVE_HI])  # 相对 196 的下标
    legal_src = {int(i) // 7 for i in rel}
    assert legal_src == {0, 1, 2}
    assert int(rel.size) == 6

    before = _board_card_ids(game)
    game.step(0, A.encode(A.Move(src=0, to=1)))
    after = _board_card_ids(game)
    assert before != after  # 顺序真的变了
    assert sorted(before) == sorted(after)
    assert after == [before[1], before[0], before[2]]

    # from == to 必须被拒绝
    with pytest.raises(ValueError):
        game.step(0, A.encode(A.Move(src=0, to=0)))


# ── 3. 训练采样：换位不被过滤 ──────────────────────────────────────────────
def test_ppo_selfplay_samples_legal_move_without_filtering():
    pytest.importorskip("torch")
    from hsbg.az.train.ppo import CollectConfig, PPOSelfPlayPolicy

    game = _fresh_recruit_game(seed=7, turn=2)
    assert game.inject_board(0, [[1, 2, 2], [2, 3, 3], [3, 1, 1]], 4).get("applied") is True
    mask = _mask(game, 0)
    target = A.encode(A.Move(src=1, to=2))
    assert bool(mask[target])

    class _MoveOnlyEvaluator:
        """把行为分布全部压在 ``target``（换位）上的叶评估器。"""

        def __call__(self, features, cards, mask, seat=0):
            prior = np.zeros(A.N_ACTIONS, dtype=np.float32)
            prior[target] = 1.0
            return prior, 0.0

    class _DummyModel:
        """只为满足 ``model.eval()`` 调用；决策走 ``eval_fn``。"""

        def eval(self):
            return self

        def to(self, device):
            return self

    cfg = CollectConfig(games=1, seed=0, opponent="bot", behavior="net", fast_act=False)
    policy = PPOSelfPlayPolicy(_DummyModel(), device="cpu", config=cfg,
                              eval_fn=_MoveOnlyEvaluator(), move_model=False)
    policy.game_id = 0
    policy.reset()
    dec = policy.decide(game, 0)
    assert int(dec.action) == target
    rec = policy.records[-1]
    assert int(rec["action"]) == target
    assert bool(rec["mask"][target]) and not bool(rec["forced"])
    assert rec["old_logprob"] == pytest.approx(0.0, abs=1e-4)


# ── 4. 竞技场适配：索引原样透传（不丢弃、不改写）───────────────────────────
def test_arena_agent_returns_move_index_unchanged(monkeypatch):
    torch = pytest.importorskip("torch")
    import scripts.arena_agent as AA
    from hsbg.az.train import ppo

    def _fake_load() -> None:
        AA._state.update({"model": object(), "torch": torch, "device": "cpu",
                          "map": {}, "ckpt": "<test>"})

    monkeypatch.setattr(AA, "_load", _fake_load)

    calls = {}

    class _FakeForward:
        def __call__(self, model, x, c, m):
            calls["mask_true"] = int(m.sum().item())
            values = torch.full((1, A.N_ACTIONS), -50.0)
            values[0, 202] = 9.0   # Move{from:1,to:0}
            values[0, 0] = 5.0     # EndTurn 也合法但分数更低
            return (values,)

    monkeypatch.setattr(ppo, "forward_model", _FakeForward())
    monkeypatch.setattr(ppo, "split_model_outputs", lambda out: (out[0], None, None))

    mask = np.zeros(A.N_ACTIONS, dtype=np.uint8)
    mask[0] = 1     # EndTurn 合法
    mask[202] = 1   # Move{1,0} 合法
    obs = {"features": np.zeros(3227, dtype=np.float32),
           "cards": np.zeros(124, dtype=np.int64),
           "action_mask": mask}
    action = int(AA.act(obs, {}))
    assert action == 202, "换位索引必须原样返回，不能被丢弃/改成 EndTurn"
    assert calls["mask_true"] == 2

    # 只有换位合法时（EndTurn 不在 mask 里）也必须返回换位，而不是 0
    mask2 = np.zeros(A.N_ACTIONS, dtype=np.uint8)
    mask2[197] = 1
    obs2 = dict(obs, action_mask=mask2)
    monkeypatch.setattr(ppo, "forward_model",
                        lambda model, x, c, m: (torch.full((1, A.N_ACTIONS), -50.0),))
    assert int(AA.act(obs2, {})) == 197
