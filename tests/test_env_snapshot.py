"""``tests/test_env_snapshot.py`` —— 环境级精确存档/恢复验收（WS5）。

覆盖（契约见 ``docs/ENV_SNAPSHOT.md``）：

1. ``snapshot`` **不改变** env（digest / obs / 候选 / 监听器数 / 策略实例）；
2. ``restore`` 后 ``obs``/候选/``_stats``/``_all_heroes`` 别名逐位恢复；
3. **语义验收**：snapshot→（继续跑）→restore→相同动作序列，与「不
   snapshot 的原始轨迹」逐步一致（观测结构/奖励/终止/info）；
4. 快照不可变 + 恢复幂等（同一快照反复 restore 结果一致）；
5. ``clone_env`` 独立副本（互不影响、轨迹一致）；
6. 事件监听重绑：恢复后继续到淘汰/终局，名次/info 与原始轨迹一致；
7. 不可快照状态（reset 前 / terminated 后 / close 后）明确抛错；
8. 目标 env 构造配置不兼容时抛错；
9. ``canonical_observation``：把**引擎随机产物**（uuid 派生的
   ``entity_id`` / PendingChoice.kind 内嵌 uuid，见 OBS-DET-1）归一化，
   用于跨轨迹比较；
10. 性能冒烟（宽松上界，防止病态回退）。

测试用**确定性动作选择**（优先级表），不引入额外随机源；每局
``reset(seed)`` 后轨迹由 seed + 动作序列完全决定。
"""

from __future__ import annotations

import dataclasses

import pytest

from hsbg.env import driver
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.env.invariants import state_digest
from hsbg.env.snapshot import (
    EnvSnapshot,
    SnapshotError,
    canonical_observation,
    clone_env,
    restore,
    snapshot,
)

_ACTION_PRIORITY = (
    "buy", "play_minion", "play_spell", "reroll", "upgrade",
    "hero_power", "activate", "use_dark_gift", "freeze",
    "move_minion", "end_turn",
)

_INFO_KEYS = ("turn", "rank", "health", "armor", "alive_count",
              "invalid", "terminated_reason", "episode_steps", "phase")


# ══════════════════════════════════════════════════════════════════════
# 测试工具
# ══════════════════════════════════════════════════════════════════════


def pick_action(env: BattlegroundsEnv) -> int | None:
    actions = env.legal_actions()
    if not actions:
        return None
    for kind in _ACTION_PRIORITY:
        for index, candidate in enumerate(actions):
            if candidate.kind == kind:
                return index
    return len(actions) - 1


def advance(env: BattlegroundsEnv, steps: int) -> None:
    for _ in range(steps):
        index = pick_action(env)
        if index is None:
            break
        _obs, _r, terminated, truncated, _info = env.step(index)
        if terminated or truncated:
            break


def replay(env: BattlegroundsEnv, steps: int) -> list:
    """执行确定性动作序列，返回可跨轨迹比较的轨迹。"""
    trace = []
    for _ in range(steps):
        index = pick_action(env)
        if index is None:
            break
        obs, reward, terminated, truncated, info = env.step(index)
        trace.append((
            int(obs.turn), str(obs.phase),
            canonical_observation(obs),
            tuple(c.signature() for c in obs.candidates),
            round(float(reward), 9), bool(terminated), bool(truncated),
            tuple((key, info.get(key)) for key in _INFO_KEYS),
        ))
        if terminated or truncated:
            break
    return trace


def make_env(seed: int = 0, opponent: str = "heuristic",
             players: int = 8) -> BattlegroundsEnv:
    env = BattlegroundsEnv(num_players=players, opponent=opponent,
                           seed=seed, max_turns=40)
    env.reset(seed=seed)
    return env


def snapshot_at(seed: int, steps: int, *, opponent: str = "heuristic",
                players: int = 8) -> tuple[BattlegroundsEnv, EnvSnapshot]:
    env = make_env(seed=seed, opponent=opponent, players=players)
    advance(env, steps)
    return env, snapshot(env)


# ══════════════════════════════════════════════════════════════════════
# 1) snapshot 不改变 env
# ══════════════════════════════════════════════════════════════════════


def test_snapshot_does_not_mutate_env() -> None:
    env, _snap_unused = snapshot_at(seed=3, steps=12)
    try:
        digest0 = state_digest(env.game)
        rng0 = env.game.rng._rng.getstate()
        obs0 = env.current_observation
        candidates0 = tuple(c.signature() for c in env.legal_actions())
        listener_count0 = sum(len(v) for v in
                              env.game.events._listeners.values())
        policies0 = [id(p) for p in env._policies]
        snap = snapshot(env)
        assert isinstance(snap, EnvSnapshot)
        assert state_digest(env.game) == digest0
        assert env.game.rng._rng.getstate() == rng0
        assert env.current_observation is obs0
        assert tuple(c.signature() for c in env.legal_actions()) == candidates0
        assert sum(len(v) for v in env.game.events._listeners.values()) \
            == listener_count0
        assert [id(p) for p in env._policies] == policies0
    finally:
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 2) restore 精确恢复
# ══════════════════════════════════════════════════════════════════════


def test_restore_recovers_exact_state() -> None:
    env, snap = snapshot_at(seed=1, steps=14)
    try:
        advance(env, 9)                       # 把 env 推到别的状态
        restore(env, snap)
        assert env.current_observation == snap.obs
        assert tuple(c.signature() for c in env.legal_actions()) \
            == snap.candidates
        assert dict(env.stats) == dict(snap.stats)
        assert env._all_heroes is env.game.heroes, "大厅视图别名必须保持"
        assert state_digest(env.game) == snap.game_digest
        # 快照不可变：restore 之后 digest 仍与创建时一致
        assert state_digest(snap.game) == snap.game_digest
        # 监听器已重绑到目标 env（不是快照时的“幽灵 env”）
        bound = 0
        for items in env.game.events._listeners.values():
            for listener in items:
                callback = listener.callback
                if getattr(callback, "__self__", None) is env:
                    bound += 1
                    assert listener.owner is env.agent_hero
        assert bound >= 2, "HERO_ELIMINATED / COMBAT_END 监听器应重绑到 env"
    finally:
        env.close()


def test_restore_is_idempotent() -> None:
    env, snap = snapshot_at(seed=2, steps=16)
    try:
        restore(env, snap)
        digest1 = state_digest(env.game)
        obs1 = env.current_observation
        restore(env, snap)
        assert state_digest(env.game) == digest1
        assert env.current_observation == obs1
        assert state_digest(snap.game) == snap.game_digest
    finally:
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 3) 语义验收：snapshot→restore→同动作序列与原始轨迹逐步一致
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("seed", "steps", "opponent"), [
    (0, 8, "heuristic"),
    (1, 12, "heuristic"),
    (3, 10, "random"),
])
def test_replay_matches_original_trajectory(seed: int, steps: int,
                                            opponent: str) -> None:
    """核心验收：恢复后继续推进的观测/奖励/终止/info 与原始轨迹一致。

    观测先经 ``canonical_observation`` 归一化引擎随机 uuid 派生字段
    （OBS-DET-1，见 docs §5.4）；奖励/候选/终止/info 为**逐位**比较。
    """
    env, snap = snapshot_at(seed=seed, steps=steps, opponent=opponent)
    try:
        original = replay(env, 22)            # 不 snapshot 的原始轨迹
        restore(env, snap)
        assert env.current_observation == snap.obs
        restored = replay(env, 22)
        assert len(restored) == len(original), (len(restored), len(original))
        for index, (expected, actual) in enumerate(zip(original, restored)):
            if expected != actual:
                for field, (want, got) in enumerate(zip(expected, actual)):
                    if want != got:
                        name = ("turn", "phase", "obs", "candidates",
                                "reward", "terminated", "truncated", "info")[field]
                        raise AssertionError(
                            f"恢复后第 {index} 步 {name} 不一致: "
                            f"{want!r} != {got!r}")
    finally:
        env.close()


def test_after_restore_reaches_same_elimination_outcome() -> None:
    """恢复后继续到终局：名次/淘汰顺序/存活数/回合与原始一致。"""
    env, snap = snapshot_at(seed=3, steps=8, opponent="random")
    try:
        original = replay(env, 60)
        restore(env, snap)
        restored = replay(env, 60)
        assert len(restored) == len(original)
        # 全轨迹（含终局 info.rank/alive_count/terminated_reason）一致
        for expected, actual in zip(original, restored):
            assert expected[4:] == actual[4:], (expected[4:], actual[4:])
            assert expected[2] == actual[2]
        assert env._all_heroes is env.game.heroes
    finally:
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 4) clone_env
# ══════════════════════════════════════════════════════════════════════


def test_clone_env_independent_and_same_trajectory() -> None:
    env, _snap_unused = snapshot_at(seed=3, steps=10)
    try:
        twin = clone_env(env)
        try:
            assert twin is not env
            assert twin.current_observation == env.current_observation
            assert twin.game is not env.game
            digest_source = state_digest(env.game)
            # 推进 twin 不改变源 env
            advance(twin, 3)
            assert state_digest(env.game) == digest_source
        finally:
            twin.close()
        # 源 env 与另一份 clone 走相同动作序列 → 轨迹一致
        twin2 = clone_env(env)
        try:
            original = replay(env, 14)
            restored = replay(twin2, 14)
            assert len(restored) == len(original)
            for expected, actual in zip(original, restored):
                assert expected == actual
        finally:
            twin2.close()
    finally:
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 5) 边界/错误路径
# ══════════════════════════════════════════════════════════════════════


def test_snapshot_rejects_unsupported_states() -> None:
    env = BattlegroundsEnv(num_players=4, seed=0)
    try:
        with pytest.raises(SnapshotError):
            snapshot(env)                       # reset 之前
        env.reset(seed=0)
        # 推进到终局
        while not env._done:
            index = pick_action(env)
            if index is None:
                break
            _obs, _r, terminated, truncated, _info = env.step(index)
            if terminated or truncated:
                break
        assert env._done
        with pytest.raises(SnapshotError):
            snapshot(env)                       # terminated 之后
        env.close()
        with pytest.raises(SnapshotError):
            snapshot(env)                       # close 之后
    finally:
        if not env._closed:
            env.close()


def test_restore_rejects_incompatible_target_env() -> None:
    env4, snap4 = snapshot_at(seed=0, steps=3, players=4)
    env8 = make_env(seed=0, players=8)
    try:
        with pytest.raises(SnapshotError):
            restore(env8, snap4)                # 4 人局快照恢复进 8 人 env
    finally:
        env4.close()
        env8.close()


# ══════════════════════════════════════════════════════════════════════
# 6) canonical_observation（OBS-DET-1 归一化）
# ══════════════════════════════════════════════════════════════════════


def test_canonical_observation_normalizes_random_ids() -> None:
    """同 seed + 同动作序列的两局：原始 obs 的 uuid 派生字段不同，
    归一化后结构完全一致（证明随机性只来自 uuid4，非行为）。"""
    env_a = make_env(seed=5)
    env_b = make_env(seed=5)
    try:
        advance(env_a, 4)
        advance(env_b, 4)
        obs_a = env_a.current_observation
        obs_b = env_b.current_observation
        # 原始 obs 至少有一处 uuid 派生差异（entity_id）
        assert obs_a != obs_b
        canon_a = canonical_observation(obs_a)
        canon_b = canonical_observation(obs_b)
        assert canon_a == canon_b
        # kind 内嵌 uuid 也归一化
        tok = obs_a.pending_choice
        if tok is not None:
            fixed = dataclasses.replace(
                tok, kind=canonical_observation(obs_a).pending_choice.kind)
            assert ":" not in fixed.kind or "<uuid>" in fixed.kind
    finally:
        env_a.close()
        env_b.close()


# ══════════════════════════════════════════════════════════════════════
# 7) 性能冒烟（宽松上界；实测数字见 docs/ENV_SNAPSHOT.md §6）
# ══════════════════════════════════════════════════════════════════════


def test_snapshot_restore_performance_smoke() -> None:
    import time

    env, snap = snapshot_at(seed=0, steps=20)
    try:
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            snap2 = snapshot(env)
            timings.append((time.perf_counter() - start) * 1000.0)
            start = time.perf_counter()
            restore(env, snap2)
            timings.append((time.perf_counter() - start) * 1000.0)
        assert max(timings) < 500.0, f"snapshot/restore 病态变慢: {timings}"
        assert snap is not None
    finally:
        env.close()

# ══════════════════════════════════════════════════════════════════════
# 8) 精确动作掩码验收（每个候选都被引擎接受且状态推进）
# ══════════════════════════════════════════════════════════════════════


def _clone_agent_and_descriptors(env):
    """在 ``model.clone(env.game)`` 上重建当前步的动作描述符（不污染主局）。"""
    from hsbg.env import driver as _driver
    from hsbg.planning.model import clone as _clone

    game = _clone(env.game)
    agent = next(h for h in game.heroes if h.uuid == env.agent_hero.uuid)
    pending = None
    if game.pending_choices:
        head = game.pending_choices[0]
        if getattr(head, "owner", None) is agent:
            pending = head
    if pending is not None:
        zones = _driver.collect_zones(game, agent)
        descriptors = _driver.enumerate_choice(game, pending, zones)
    else:
        descriptors = _driver.enumerate_step(
            game, agent, _driver.collect_zones(game, agent)).descriptors
    return game, agent, descriptors


@pytest.mark.parametrize(("seed", "steps"), [(0, 5), (0, 12), (1, 8)])
def test_exact_action_mask_every_candidate_accepted(seed: int,
                                                    steps: int) -> None:
    """``legal_actions()/action_mask()`` 的每个候选都被引擎接受且状态推进。

    * 全候选在 ``clone(game)`` 上逐个尝试（不污染主局）；
    * 候选签名序列与独立重建的描述符**长度/顺序一致**（唯一性 + 无越界）；
    * 非 end_turn：``driver.apply_action`` 返回 success 且（应用后）状态有
      变化；end_turn 由引擎 ``apply_action`` 直接返回 True（推进发生在
      env 层）→ 用 ``clone_env`` 隔离跑一步，断言回合推进或终局；
    * 非法/外部候选：``env.step`` 返回 ``invalid=True`` 且状态不推进。
    """
    from hsbg.env import driver as _driver
    from hsbg.env.invariants import state_digest

    env = make_env(seed=seed)
    try:
        advance(env, steps)
        actions = env.legal_actions()
        mask = env.action_mask()
        assert len(mask) == len(actions) and all(mask)
        signatures = [c.signature() for c in actions]
        assert len(signatures) == len(set(signatures)), "候选签名重复"

        game, agent, descriptors = _clone_agent_and_descriptors(env)
        assert [d.to_candidate().signature() for d in descriptors] \
            == signatures, "候选与独立枚举的长度/顺序不一致"
        for index in range(len(descriptors)):
            # 描述符引用实体对象：必须应用在**同一份 clone**（重新枚举）上
            game, agent, fresh_descriptors = _clone_agent_and_descriptors(env)
            descriptor = fresh_descriptors[index]
            assert descriptor.to_candidate().signature() == signatures[index]
            before = state_digest(game)
            result = _driver.apply_action(game, agent, descriptor)
            assert result.success, (
                f"候选 {index} {descriptor.kind!r} 被引擎拒绝: "
                f"{result.error_type}: {result.error}")
            if descriptor.kind != "end_turn":
                assert state_digest(game) != before, (
                    f"候选 {index} {descriptor.kind!r} 成功但状态未推进")

        # end_turn 的“推进”在 env 层：用 clone_env 隔离验证
        end_index = next(
            (i for i, c in enumerate(actions) if c.kind == "end_turn"), None)
        if end_index is not None:
            twin = clone_env(env)
            try:
                before_turn = int(twin.game.turn)
                _obs, _r, term, trunc, _info = twin.step(end_index)
                assert term or trunc or int(twin.game.turn) > before_turn
            finally:
                twin.close()

        # 非法/外部候选不得被当作合法动作：状态不推进
        digest0 = state_digest(env.game)
        obs0 = env.current_observation
        foreign = dataclasses.replace(actions[0], src_slot=999, tgt_slot=999)
        _obs, _r, term, trunc, info = env.step(foreign)
        assert info.get("invalid") is True and not term
        assert state_digest(env.game) == digest0
        assert env.current_observation is obs0
    finally:
        env.close()

