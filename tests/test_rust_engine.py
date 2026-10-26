"""HSBRSIM 主 Rust 引擎 ``hsbg_engine``（vendored TavernGym fork）回归测试。

覆盖范围（对应 ``rust/FORK.md`` / ``docs/RUST_ENGINE.md`` 的验收清单）：

1. import / 版本 / 数据概况（``data_info``，数据替换后自动跟随 meta）；
2. 动作/观测布局常量（245 动作 / 3227 floats / 124 cards，与 AutoTavern 对齐）；
3. 单局 8 人 bot 对局：完整 placements（1..8 排列）与 ``run_bot_games``；
4. ``BattlegroundsEnv`` 包装层：观测形状/dtype、跑到终局、placement 奖励范围；
5. ``BatchEnv`` 冒烟：观测形状、逐步推进、save/load 往返；
6. ``action_name`` / ``layout`` 与上游 ``taverngym`` 逐项相等（上游缺失自动 skip）；
7. 同 seed 确定性（SoloEnv 轨迹 + Game 全量 state_json）；
8. ``state_json`` 往返（字节相等 + 恢复后观测/续跑一致）；
9. 与上游逐位一致（同数据版本时：run_bot_games 终局回合、全 bot 对局 state_json
   字节相等）；上游缺失或数据版本不同（如 37.0.0 数据替换后）自动 skip。

运行::

    python3 -m pytest tests/test_rust_engine.py -q
"""

from __future__ import annotations

import json

import numpy as np
import pytest

hsbg_engine = pytest.importorskip(
    "hsbg_engine",
    reason="hsbg_engine 未安装（Rust 引擎需 `cd rust && python3 -m pip install -e .`）",
)

from hsbg_engine import (  # noqa: E402
    N_ACTIONS,
    N_CARDS,
    OBS_CARDS,
    OBS_FLOATS,
    BatchEnv,
    BattlegroundsEnv,
    Game,
    SoloEnv,
    action_name,
    build_info,
    build_is_current,
    data_info,
    game_version,
    layout,
    run_bot_games,
    server_rules_version,
    turn_search,
    version,
)

#: 上游参照实现（可选依赖；未安装时相关用例 skip）
try:  # pragma: no cover - 取决于环境
    import taverngym
except ImportError:  # pragma: no cover
    taverngym = None

requires_upstream = pytest.mark.skipif(
    taverngym is None,
    reason="上游 taverngym 未安装（可选参照，见 docs/TAVERNGYM_BACKEND.md）",
)

#: 同数据版本才能做逐位对拍（数据替换成 37.0.0 后上游仍是 36.6.3，只保留布局对比）
same_data_as_upstream = bool(
    taverngym is not None
    and taverngym.game_version() == game_version()
    and taverngym.N_CARDS == N_CARDS
)
requires_same_data = pytest.mark.skipif(
    not same_data_as_upstream,
    reason="上游 taverngym 未安装，或两边数据版本/卡表不同（数据替换后属预期）",
)

#: 动作/观测布局是 AT 对齐的固定契约（不随数据替换变化）
N_ACTIONS_EXPECTED = 245
OBS_FLOATS_EXPECTED = 3227
OBS_CARDS_EXPECTED = 124
NUM_PLAYERS = 8


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def _mask(env) -> np.ndarray:
    """``SoloEnv.legal_mask()``（bytes）-> bool 数组。"""
    return np.frombuffer(env.legal_mask(), dtype=np.uint8).astype(bool)


def _lowest_legal(env) -> int:
    """取最小合法动作下标（确定性驱动，不引入额外随机源）。"""
    flat = np.flatnonzero(_mask(env))
    assert flat.size > 0, "需要行动时至少应有一个合法动作"
    return int(flat[0])


def _run_game_to_end(game: Game, limit: int = 1000) -> Game:
    """用引擎内置 bot 驱动全部座位直到终局（每轮所有需要行动的座位各走一步）。"""
    guard = 0
    while not game.is_over() and guard < limit:
        guard += 1
        acted = False
        for p in range(game.num_players):
            if game.needs_action(p):
                game.bot_play(p)
                acted = True
        if not acted:  # 防御：驱动停摆时不进死循环
            break
    return game


def _solo_rollout(seed: int, steps: int = 200):
    """SoloEnv 确定性 rollout：返回（轨迹, 终态 state_json）。"""
    env = SoloEnv(seed, None, 0)
    traj = []
    for _ in range(steps):
        a = _lowest_legal(env)
        reward, done, illegal = env.step(a)
        traj.append((a, round(float(reward), 6), bool(done), illegal, env.turn, env.placement))
        if done:
            break
    return traj, env.state_json()


# ══════════════════════════════════════════════════════════════════════
# 1. import / 版本 / 数据概况
# ══════════════════════════════════════════════════════════════════════


def test_import_and_versions():
    """包可 import，版本/构建信息齐全，数据概况与 meta 一致。"""
    assert version() == "1.0.0"  # fork 保留上游版本号（公开 API 逐位一致）
    assert isinstance(game_version(), str) and game_version().count(".") >= 2
    assert isinstance(server_rules_version(), str) and server_rules_version()

    info = build_info()
    assert set(info) == {"source_hash", "profile", "file"}
    assert info["profile"] == "release"
    assert len(info["source_hash"]) == 16
    assert all(c in "0123456789abcdef" for c in info["source_hash"])
    assert info["file"].endswith((".so", ".pyd", ".dylib"))
    # 从源码 editable 安装时应为 True；非 editable 安装无法判断时为 None。
    assert build_is_current() in (True, None)


def test_data_info_matches_meta():
    """``data_info()`` 反映当前编译进来的卡表（数据替换后应跟随新数据 meta）。"""
    info = data_info()
    assert set(info) == {"cards", "game_version", "server_rules_version", "n_cards"}
    assert info["n_cards"] > 3000
    # N_CARDS = 卡表条数 + 1 个空位（卡表稠密，CardId 即下标）
    assert info["cards"] == info["n_cards"] - 1
    assert info["game_version"] == game_version()
    assert info["server_rules_version"] == server_rules_version()


def test_action_and_observation_layout_constants():
    """245 动作 / 3227 floats / 124 cards 布局固定（不随卡牌数据替换变化）。"""
    assert N_ACTIONS == N_ACTIONS_EXPECTED
    assert OBS_FLOATS == OBS_FLOATS_EXPECTED
    assert OBS_CARDS == OBS_CARDS_EXPECTED
    assert N_CARDS > 3000

    m = dict(layout())
    assert len(m) == 32
    assert m["N_ACTIONS"] == N_ACTIONS
    assert m["OBS_FLOATS"] == OBS_FLOATS
    assert m["OBS_CARDS"] == OBS_CARDS
    # 动作布局自洽：最后一段 move（7x7，棋盘槽位 -> 插入位置）正好填满 245
    assert m["A_MOVE"] + m["N_BOARD"] * m["N_BOARD"] == N_ACTIONS
    assert m["A_PLAY"] == 46 and m["A_MAGNETIZE"] == 126

    # 每个动作下标都有可读名，越界抛 ValueError
    names = [action_name(a) for a in range(N_ACTIONS)]
    assert len(set(names)) == N_ACTIONS
    assert "EndTurn" in names[0]
    with pytest.raises(ValueError):
        action_name(N_ACTIONS)


# ══════════════════════════════════════════════════════════════════════
# 2. 单局 8 人 bot 对局
# ══════════════════════════════════════════════════════════════════════


def test_single_bot_game_placements():
    """完整 8 人 bot 对局：终局 placements 是 1..8 的排列。"""
    g = _run_game_to_end(Game(0))
    assert g.num_players == NUM_PLAYERS
    assert g.is_over()
    placements = list(g.placements())
    assert sorted(placements) == list(range(1, NUM_PLAYERS + 1))
    assert g.turn >= 1
    assert g.state_json()  # 终局状态仍可序列化
    json.loads(g.state_json())


def test_run_bot_games_returns_final_turns():
    """``run_bot_games`` 多局驱动（GIL 释放）返回每局终局回合数。"""
    turns = run_bot_games(3, seed=0)
    assert len(turns) == 3
    assert all(t > 0 for t in turns)
    # 同 seed 完全可复现（引擎行为由 seed 决定）
    assert run_bot_games(3, seed=0) == turns
    assert run_bot_games(2, seed=123) != turns[:2]


def test_battlegrounds_env_single_episode():
    """``BattlegroundsEnv``（Gym 风格包装）跑完一局：观测形状/dtype、终局 rank。"""
    env = BattlegroundsEnv(seed=0)
    obs, info = env.reset(seed=0)
    assert info["turn"] == 0
    assert obs["features"].shape == (OBS_FLOATS,)
    assert obs["features"].dtype == np.float32
    assert obs["cards"].shape == (OBS_CARDS,)
    assert obs["cards"].dtype == np.int32
    assert obs["action_mask"].shape == (N_ACTIONS,)
    assert obs["action_mask"].dtype == np.bool_
    assert env.observation_sizes == {
        "features": OBS_FLOATS,
        "cards": OBS_CARDS,
        "action_mask": N_ACTIONS,
    }

    total_reward = 0.0
    steps = 0
    while steps < 4000:
        action = int(np.flatnonzero(obs["action_mask"])[0])
        obs, reward, done, truncated, info = env.step(action)
        total_reward += float(reward)
        steps += 1
        assert not info["illegal"]
        if done or truncated:
            break
    assert done and not truncated
    assert info["placement"] in range(1, NUM_PLAYERS + 1)
    # 名次奖励：第 1 名 +1、最后 -1，中间步为 0
    expected = 1.0 - 2.0 * (info["placement"] - 1) / (NUM_PLAYERS - 1)
    assert abs(total_reward - expected) < 1e-4
    state = env.state_json()
    assert json.loads(state)


# ══════════════════════════════════════════════════════════════════════
# 3. BatchEnv 冒烟
# ══════════════════════════════════════════════════════════════════════


def test_batch_env_smoke():
    """``BatchEnv``：观测形状、多局推进、save/load 精确往返。"""
    env = BatchEnv(n_games=4, seed=0, controlled=(0,), threads=2)
    assert env.n_games == 4
    assert env.n_slots == 4
    assert env.controlled == (0,)
    assert abs(env.illegal_penalty - (-0.01)) < 1e-6  # 上游默认值

    obs = env.observe()
    assert obs["features"].shape == (4, OBS_FLOATS)
    assert obs["cards"].shape == (4, OBS_CARDS)
    assert obs["action_mask"].shape == (4, N_ACTIONS)
    assert obs["ready"].shape == (4,)
    assert obs["features"].dtype == np.float32
    assert obs["cards"].dtype == np.int32
    assert obs["action_mask"].dtype == np.bool_

    finished = 0
    for _ in range(40):
        actions = [
            int(np.flatnonzero(obs["action_mask"][i])[0])
            if obs["action_mask"][i].any()
            else 0
            for i in range(env.n_slots)
        ]
        rewards, dones, info = env.step(actions)
        assert rewards.shape == (4,)
        assert dones.shape == (4,)
        assert info["placement"].shape == (4,)
        assert not info["rejected"].any()
        finished += int(dones.sum())
        obs = env.observe()
    assert finished >= 1  # 40 步内应有座位走完一局（bot 对局约 15 回合）

    state = env.save(0)
    json.loads(state)
    env.load(0, state)
    assert env.save(0) == state  # save -> load -> save 字节相等
    assert env.game(0).num_players == NUM_PLAYERS


# ══════════════════════════════════════════════════════════════════════
# 4. 与上游 taverngym 的 API 对齐（可选依赖）
# ══════════════════════════════════════════════════════════════════════


@requires_upstream
def test_layout_and_action_names_match_upstream():
    """``layout()`` / ``action_name(a)`` 与上游逐项相等（仅改包名，不改布局）。"""
    assert layout() == taverngym.layout()
    assert N_ACTIONS == taverngym.N_ACTIONS
    assert OBS_FLOATS == taverngym.OBS_FLOATS
    assert OBS_CARDS == taverngym.OBS_CARDS
    assert version() == taverngym.version()
    for a in range(N_ACTIONS):
        assert action_name(a) == taverngym.action_name(a), f"动作下标 {a} 名称不一致"


@requires_same_data
def test_bit_identical_to_upstream_same_data():
    """同数据版本时与上游逐位一致：bot 对局回合数 + 全量 state_json 字节相等。"""
    for seed in (0, 7):
        assert run_bot_games(3, seed=seed) == taverngym.run_bot_games(3, seed=seed)

    ours = _run_game_to_end(Game(0))
    theirs = _run_game_to_end(taverngym.Game(0))
    assert ours.state_json() == theirs.state_json()
    assert list(ours.placements()) == list(theirs.placements())

    # 同一座位、同一阶段的官方观测（floats + cards）也逐字节一致
    f1, c1 = ours.observe(0)
    f2, c2 = theirs.observe(0)
    assert f1 == f2 and c1 == c2


# ══════════════════════════════════════════════════════════════════════
# 5. 确定性
# ══════════════════════════════════════════════════════════════════════


def test_same_seed_determinism():
    """同 seed + 同动作序列 ⇒ 轨迹与 state_json 完全一致。"""
    traj_a, state_a = _solo_rollout(0)
    traj_b, state_b = _solo_rollout(0)
    assert traj_a == traj_b
    assert state_a == state_b

    game_a = _run_game_to_end(Game(3))
    game_b = _run_game_to_end(Game(3))
    assert game_a.state_json() == game_b.state_json()
    assert list(game_a.placements()) == list(game_b.placements())

    # 不同 seed 必须产生不同对局
    assert _solo_rollout(1)[1] != state_a


# ══════════════════════════════════════════════════════════════════════
# 6. state_json 往返
# ══════════════════════════════════════════════════════════════════════


def test_state_json_roundtrip():
    """``state_json`` -> ``from_json`` 逐位还原，恢复后观测与续跑结果一致。"""
    game = Game(7)
    for _ in range(3):  # 推进到早中期（英雄选择 + 前几个招募回合）
        for p in range(game.num_players):
            if game.needs_action(p):
                game.bot_play(p)

    payload = game.state_json()
    json.loads(payload)
    restored = Game.from_json(payload)
    assert restored.state_json() == payload

    # 恢复后官方观测逐字节一致
    assert restored.observe(0) == game.observe(0)
    assert restored.placements() == game.placements()

    # 两边各自续跑到终局，状态逐位一致
    _run_game_to_end(game)
    _run_game_to_end(restored)
    assert game.is_over() and restored.is_over()
    assert game.state_json() == restored.state_json()
    assert list(game.placements()) == list(restored.placements())


def test_turn_search_api_smoke():
    """Rust TurnSearch PyO3 API：合法动作 + 状态预算 + pairwise 计数。"""
    game = Game(70000)
    for p in range(game.num_players):
        if game.needs_action(p):
            game.step(p, game.bot_action(p))
    for _ in range(12):
        legal = np.frombuffer(game.legal_mask(0), dtype=np.uint8).astype(bool)
        if legal[0] or not game.needs_action(0):
            break
        game.step(0, game.bot_action(0))

    raw, action, score, n_states, n_combats = turn_search(
        game, 0, states_budget=4, samples_per_action=1,
        combat_samples=1, max_steps_per_turn=12, seed=1,
    )
    scores = np.frombuffer(raw, dtype="<f4")
    legal = np.frombuffer(game.legal_mask(0), dtype=np.uint8).astype(bool)
    assert scores.shape == (N_ACTIONS,)
    assert 0 <= action < N_ACTIONS
    assert bool(legal[action])
    assert n_states >= 1 and n_states <= 4
    assert n_combats >= 0
    assert np.isfinite(score)
