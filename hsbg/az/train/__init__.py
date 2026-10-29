"""``hsbg.az.train`` —— AlphaZero 初期自对弈/训练/评测脚手架（task-3）。

模块：
- ``common``     固定形状/动作分段/名次效用/引擎惰性加载/数组工具；
- ``policies``   策略集合（random / engine bot / heuristic / net / Rust MCTS / AZ PIMC）；
- ``evaluators`` 搜索叶评估器（uniform / heuristic / net）；
- ``model``      轻量策略+名次价值网络（torch，3227→256→{245,8}）与 checkpoint；
- ``data``       (features, cards, mask, pi, action, rank/z) 数据集与质量指标；
- ``selfplay``   BatchEnv / Game 两条 8 座自对弈与轨迹采集路径；
- ``train_loop`` 策略 CE + 名次价值 CE 的初期训练（loss/吞吐）与监督评估；
- ``ppo``        MCTS 引导的 PPO（masked、clip、GAE、KL 早停）与自对弈采集；
- ``seq_aux``    动作序列辅助任务：turn 内动作 multi-hot 标签、权重 ramp、BCE 损失
                 （默认关闭，见 docs/ACTION_SEQUENCE_AUX.md）；
- ``bc_aux``     真实人类对局 BC 辅助正则（小权重辅助 CE，默认关闭，见 docs/BC_AUX.md）；
- ``evaluate``   固定 seed 策略评测（rank/top4/win/legal/truncated/耗时）；
- ``report``     JSON 报告 schema（``hsbg.az.eval/v1`` / ``hsbg.az.train_smoke/v1``）。

约束：只复用 ``hsbg_engine`` 与 ``hsbg.az``；本包在无引擎机器上可 import（引擎相关入口惰性加载）。
"""

from __future__ import annotations

from .common import (
    DATA_VERSION,
    N_ACTIONS,
    N_PLAYERS,
    N_RANKS,
    OBS_CARDS,
    OBS_FLOATS,
    RANK_UTILITY,
    engine_available,
    engine_info,
    group_of,
    utility_from_rank,
)
from .data import AZDataset
from .evaluate import EvalConfig, evaluate_baseline, evaluate_policy, run_comparison
from .policies import (
    AZSearchPolicy,
    Decision,
    EngineBotPolicy,
    HeuristicPolicy,
    NetworkPolicy,
    Policy,
    RandomPolicy,
    RustMCTSPolicy,
    make_policy,
)
from .report import (
    EVAL_SCHEMA,
    TRAIN_SCHEMA,
    build_eval_report,
    build_train_report,
    format_summary_table,
    load_report,
    validate_eval_report,
    write_report,
)
from .selfplay import SelfPlayConfig, collect_selfplay, collect_selfplay_batch, collect_selfplay_game
from .ppo import (PPOConfig, PPOSelfPlayPolicy, collect_ppo_batch, ppo_losses, train_ppo)
from .train_loop import evaluate_supervised, train_policy_value

__all__ = [
    "DATA_VERSION",
    "N_ACTIONS",
    "N_PLAYERS",
    "N_RANKS",
    "OBS_CARDS",
    "OBS_FLOATS",
    "RANK_UTILITY",
    "engine_available",
    "engine_info",
    "group_of",
    "utility_from_rank",
    "AZDataset",
    "EvalConfig",
    "evaluate_baseline",
    "evaluate_policy",
    "run_comparison",
    "AZSearchPolicy",
    "Decision",
    "EngineBotPolicy",
    "HeuristicPolicy",
    "NetworkPolicy",
    "Policy",
    "RandomPolicy",
    "RustMCTSPolicy",
    "make_policy",
    "EVAL_SCHEMA",
    "TRAIN_SCHEMA",
    "build_eval_report",
    "build_train_report",
    "format_summary_table",
    "load_report",
    "validate_eval_report",
    "write_report",
    "SelfPlayConfig",
    "collect_selfplay",
    "collect_selfplay_batch",
    "collect_selfplay_game",
    "evaluate_supervised",
    "train_policy_value",
    "PPOConfig",
    "PPOSelfPlayPolicy",
    "collect_ppo_batch",
    "ppo_losses",
    "train_ppo",
]
