"""计划 / 搜索模块（AlphaZero 类搜索的引擎 clone / forward 原语）。

搜索侧最小接口清单（Phase 1）::

    from hsbg.planning import model, rng, checkpoint, digest, hidden

    dup = model.clone(game)                 # 快速独立副本（含闭包重绑）
    cp = checkpoint.push_checkpoint(dup)    # 快照
    game2 = checkpoint.pop_checkpoint(cp)   # 独立恢复（再 clone 快照）
    acts = model.legal_actions(dup, hero)
    model.apply(dup, hero, acts[0])
    st = rng.get_state(game.rng); rng.set_state(game.rng, st)
    fork = rng.fork(game.rng)
    summary, dup_after = model.simulate_combat(dup, hero_a, hero_b,
                                               keep_state=True)
    key = digest.digest(dup)                # 状态摘要（去重/断言）
    hidden.inject_hidden_state(dup, hero_b, board=[...])  # determinization v0

见 ``docs/ALGORITHM_RESEARCH.md`` §4.2 / §6.3 与 ``scripts/bench_planning.py``。
"""

from hsbg.planning.model import (  # noqa: F401
    RandomRolloutPolicy,
    RolloutResult,
    apply,
    clone,
    drain_choices,
    evaluate,
    is_terminal,
    legal_actions,
    pending_choice,
    random_rollout,
    simulate_combat,
    simulate_turn_combat,
)

from hsbg.planning import live_warband  # noqa: F401
from hsbg.planning.live_warband import (  # noqa: F401
    CombatSimResult,
    PairwiseResult,
    WarbandBuild,
    build_warband,
    make_combat_game,
    normalize_entities,
    pairwise_winrate,
    predict_after_action,
    simulate_combat_warbands,
)

from hsbg.planning import checkpoint  # noqa: F401
from hsbg.planning import digest as digest_mod  # noqa: F401
from hsbg.planning import hidden  # noqa: F401
from hsbg.planning import rng  # noqa: F401
from hsbg.planning.checkpoint import (  # noqa: F401
    Checkpoint,
    CheckpointStack,
    pop_checkpoint,
    push_checkpoint,
)
from hsbg.planning.digest import digest, digest_hex  # noqa: F401
from hsbg.planning.rollout_throughput import (  # noqa: F401
    HeuristicEnginePolicy,
    RandomEnginePolicy,
    RolloutEndResult,
    benchmark_rollout,
    drive_recruit_turn,
    rollout_batch,
    rollout_to_end,
)

from hsbg.planning.rng import fork as rng_fork  # noqa: F401
from hsbg.planning.rng import get_state as rng_get_state  # noqa: F401
from hsbg.planning.rng import set_state as rng_set_state  # noqa: F401

__all__ = [
    "clone",
    "legal_actions",
    "apply",
    "drain_choices",
    "pending_choice",
    "is_terminal",
    "random_rollout",
    "evaluate",
    "RolloutResult",
    "RandomRolloutPolicy",
    "simulate_combat",
    "simulate_turn_combat",
    "Checkpoint",
    "CheckpointStack",
    "push_checkpoint",
    "pop_checkpoint",
    "digest",
    "digest_hex",
    "rng_get_state",
    "rng_set_state",
    "rng_fork",
    "rng",
    "live_warband",
    "WarbandBuild",
    "CombatSimResult",
    "PairwiseResult",
    "make_combat_game",
    "normalize_entities",
    "build_warband",
    "simulate_combat_warbands",
    "pairwise_winrate",
    "predict_after_action",
    "rollout_to_end",
    "rollout_batch",
    "benchmark_rollout",
    "HeuristicEnginePolicy",
    "RandomEnginePolicy",
    "RolloutEndResult",
    "checkpoint",
    "digest_mod",
    "hidden",
]
