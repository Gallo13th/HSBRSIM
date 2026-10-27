"""固定 seed 的搜索质量对比评测（task-3 第 3 条）。

在固定 seeds 上比较：random / engine bot / heuristic / 搜索策略（Rust MCTS、
Python MCTS 原型、或 task-2 ``hsbg.az`` 搜索），输出
``rank/胜率/前四率/合法动作率/truncated/耗时`` 到 ``runs/az_eval/report.json``；
可选做一小段搜索自对弈，记录**训练数据质量**（pi 熵/argmax 分布/合法性）。

示例（远程 dev 机）：

```bash
cd ~/projects/HSBRSIM
PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python \
  scripts/az_eval_search.py --games 20 --seed 90000 \
  --policies random,bot,heuristic,search_rust --search-sims 8 \
  --search-data-games 1 --out runs/az_eval/report.json
```

只写 ``--out``（默认 ``runs/az_eval/report.json``）与其同目录的 data npz。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train import (  # noqa: E402
    EvalConfig,
    SelfPlayConfig,
    engine_available,
    engine_info,
    make_policy,
    run_comparison,
)
from hsbg.az.train.evaluators import make_evaluator  # noqa: E402
from hsbg.az.train.model import NetEvaluator, load_checkpoint  # noqa: E402
from hsbg.az.train.report import (  # noqa: E402
    build_eval_report,
    format_summary_table,
    validate_eval_report,
    write_report,
)
from hsbg.az.train.selfplay import collect_selfplay  # noqa: E402


def _repro(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "argv": list(sys.argv),
        "cwd": os.getcwd(),
        "python": sys.executable,
        "note": "PYTHONPATH 需包含 rust/python 与仓库根目录；hsbg_engine 需先构建安装",
    }


def _search_kwargs(args: argparse.Namespace, evaluator) -> Dict[str, Any]:
    name = args.search_backend
    accepts_game = bool(getattr(evaluator, "accepts_game", False))
    base = {"simulations": args.search_sims,
            "temperature": float(args.search_temperature)}
    if name == "az":
        engine_backend = args.search_engine_backend
        if accepts_game and engine_backend == "auto":
            engine_backend = "python"   # game-aware 先验只能走 Python 搜索后端
        return {**base, "determinizations": args.search_det,
                "evaluator": evaluator, "engine_backend": engine_backend}
    return {**base, "evaluator": evaluator, "dirichlet_epsilon": 0.0}


def build_factories(args: argparse.Namespace, seed: int,
                    evaluator) -> Dict[str, Callable[[], Any]]:
    """按 --policies 构造 name -> () -> Policy 工厂（每次新建，保证评测互不污染）。"""
    factories: Dict[str, Callable[[], Any]] = {}
    for raw in str(args.policies).split(","):
        name = raw.strip()
        if not name:
            continue
        if name == "random":
            factories["random"] = lambda n=name: make_policy("random", seed=seed)
        elif name in ("bot", "engine_bot"):
            factories["bot"] = lambda: make_policy("bot")
        elif name == "heuristic":
            factories["heuristic"] = lambda: make_policy("heuristic")
        elif name in ("net", "network"):
            if evaluator is None:
                raise SystemExit("[error] --policies net 需要 --net-checkpoint")
            factories["net"] = lambda: make_policy("net", evaluator=evaluator)
        elif name.startswith("search"):
            if name in ("search_rust", "search_rust_rollout", "search_az"):
                accepts_game = bool(getattr(evaluator, "accepts_game", False))
                if accepts_game and name != "search_az":
                    raise SystemExit(
                        "[error] game-aware 先验（bot_prior/rollout）只能配 search_az"
                        "（--search-backend az --search-engine-backend python）")
                kw = _search_kwargs(args, evaluator)
                if name == "search_rust_rollout":
                    kw.pop("evaluator", None)
                    kw["rollout"] = True
                factories[name] = lambda n=name, k=kw: make_policy(n, **k)
            else:
                raise SystemExit(f"[error] 未知搜索策略 {name}")
        else:
            raise SystemExit(f"[error] 未知策略 {name}")
    if not factories:
        raise SystemExit("[error] --policies 为空")
    return factories


def _collect_search_data(args: argparse.Namespace, evaluator,
                         out_dir: str) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """可选：一小段搜索自对弈，产出训练数据质量指标（固定 seed，与评测 seed 分离）。"""
    if int(args.search_data_games) <= 0:
        return None, {"enabled": False}
    if args.search_data_policy in ("random", "heuristic", "bot"):
        pol = make_policy(args.search_data_policy, seed=int(args.seed) + 300000)
    else:
        kw = _search_kwargs(args, evaluator)
        # 数据生成用温度采样（visit 分布更有信息量）；评测用 argmax
        kw["temperature"] = float(args.search_data_temperature)
        if args.search_data_policy == "search_rust_rollout":
            kw.pop("evaluator", None)
            kw["rollout"] = True
        pol = make_policy(args.search_data_policy, seed=int(args.seed) + 300000, **kw)
    cfg = SelfPlayConfig(games=int(args.search_data_games),
                         seed=int(args.seed) + 500000, mode="game",
                         sample_stride=max(1, int(args.search_data_stride)),
                         max_steps=20000)
    t0 = time.time()
    ds, meta = collect_selfplay(pol, cfg)
    metrics = ds.quality_metrics()
    errs = ds.validate()
    data_path = os.path.join(out_dir, "search_data.npz")
    ds.save(data_path)
    payload = {
        "policy": args.search_data_policy,
        "games": int(meta.get("games", 0)),
        "samples": int(len(ds)),
        "decisions": int(meta.get("decisions", 0)),
        "illegal_actions": int(meta.get("illegal_actions", 0)),
        "truncated_games": int(meta.get("truncated_games", 0)),
        "elapsed_s": float(meta.get("elapsed_s", 0.0)),
        "games_per_s": float(meta.get("games_per_s", 0.0)),
        "data_path": data_path,
        "validate_errors": errs,
        "quality": metrics,
        "seed": int(args.seed) + 500000,
    }
    print(f"[data] search self-play {payload['games']} games, {payload['samples']} samples, "
          f"legal={metrics.get('legal_action_rate')}, "
          f"pi_entropy={metrics.get('pi_entropy_mean')}, "
          f"argmax={metrics.get('pi_argmax_group_counts')}", flush=True)
    return payload, {"enabled": True}


def main() -> int:
    ap = argparse.ArgumentParser(description="AZ 搜索质量对比评测（固定 seed）")
    ap.add_argument("--games", type=int, default=20, help="每个策略的局数（建议 10-20+）")
    ap.add_argument("--seed", type=int, default=90000, help="评测 seed 起点（与训练/自对弈分离）")
    ap.add_argument("--policies", default="random,bot,heuristic,search_rust",
                    help="逗号分隔：random,bot,heuristic,net,search_rust,search_rust_rollout,"
                         "search_az")
    ap.add_argument("--search-backend", default="rust", choices=["rust", "az"])
    ap.add_argument("--search-sims", type=int, default=8)
    ap.add_argument("--search-temperature", type=float, default=0.0,
                    help=">0 探索采样；<=0 = argmax（评测用默认 0 以保证强度）")
    ap.add_argument("--search-det", type=int, default=1)
    ap.add_argument("--search-engine-backend", default="auto",
                    choices=["auto", "rust", "python"],
                    help="hsbg.az 搜索后端；game-aware 先验(bot_prior)必须 python")
    ap.add_argument("--search-evaluator", default="heuristic",
                    choices=["heuristic", "uniform", "net", "bot_prior", "rollout"],
                    help="叶评估器；bot_prior/rollout 为 game-aware（特权/截断）先验，仅诊断用")
    ap.add_argument("--bot-prior-blend", type=float, default=0.75)
    ap.add_argument("--rollout-horizon", type=int, default=8)
    ap.add_argument("--net-checkpoint", default="")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--search-data-games", type=int, default=1,
                    help=">0 时额外用搜索策略自对弈 N 局，记录训练数据质量")
    ap.add_argument("--search-data-policy", default="",
                    help="自对弈数据策略（默认=第一个 search_* 策略；也可 random/heuristic）")
    ap.add_argument("--search-data-stride", type=int, default=1)
    ap.add_argument("--search-data-temperature", type=float, default=1.0,
                    help="数据生成温度（1.0=探索，π 为 visit 分布）")
    ap.add_argument("--out", default="runs/az_eval/report.json")
    args = ap.parse_args()

    if not engine_available():
        print("[error] hsbg_engine 不可用：需要 Rust 主引擎构建（cd rust && pip install -e .）",
              file=sys.stderr)
        return 2
    if int(args.games) < 10:
        print(f"[warn] --games={args.games} < 10：统计噪声大，建议 10-20+ 局", flush=True)
    out_dir = os.path.dirname(os.path.abspath(args.out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    eng = engine_info()
    print(f"[engine] {json.dumps(eng, ensure_ascii=False)}", flush=True)

    # 叶评估器（搜索策略用；net 需要 checkpoint；bot_prior/rollout 为 game-aware 诊断先验）
    evaluator = None
    if args.search_evaluator == "net":
        if not args.net_checkpoint:
            raise SystemExit("[error] --search-evaluator net 需要 --net-checkpoint")
        net, meta = load_checkpoint(args.net_checkpoint, device=args.device)
        evaluator = NetEvaluator(net, device=args.device,
                                 norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    elif args.search_evaluator == "bot_prior":
        from hsbg.az.policy import BotPriorEvaluator  # task-2 的 game-aware 先验

        evaluator = BotPriorEvaluator(blend=float(args.bot_prior_blend))
    elif args.search_evaluator == "rollout":
        from hsbg.az.policy import RolloutEvaluator  # task-2 的截断 rollout 价值

        evaluator = RolloutEvaluator(horizon=int(args.rollout_horizon))
    else:
        evaluator = make_evaluator(args.search_evaluator)

    factories = build_factories(args, int(args.seed), evaluator)
    print(f"[eval] policies={list(factories)} games={args.games} "
          f"seeds={args.seed}..{args.seed + args.games - 1} "
          f"search_sims={args.search_sims} evaluator={args.search_evaluator}", flush=True)
    t_eval = time.time()
    comparison = run_comparison(factories, EvalConfig(games=int(args.games),
                                                       seed=int(args.seed)))
    eval_seconds = time.time() - t_eval

    # 搜索配置写进每个策略的指标（便于复现/解释）
    backend_of = {"search_rust": "rust", "search_rust_rollout": "rust",
                  "search_az": "az"}
    for name, m in comparison["policies"].items():
        if name.startswith("search"):
            m["search_config"] = {
                "backend": backend_of.get(name, args.search_backend),
                "simulations": int(args.search_sims),
                "temperature": float(args.search_temperature),
                "determinizations": int(args.search_det),
                "evaluator": args.search_evaluator,
                "net_checkpoint": args.net_checkpoint or None,
            }

    # 可选：搜索自对弈数据质量
    data_policy = args.search_data_policy or next(
        (n for n in factories if n.startswith("search")), "heuristic")
    old_policy = args.search_data_policy
    args.search_data_policy = data_policy
    data_payload, data_meta = _collect_search_data(args, evaluator, out_dir)
    args.search_data_policy = old_policy

    report = build_eval_report(
        engine=eng,
        protocol=comparison["protocol"],
        policies=comparison["policies"],
        comparison=comparison["comparison"],
        data_quality=data_payload or {},
        repro=_repro(args),
        notes=[
            "协议：seat0=被评策略，其余 7 座=引擎内置 bot；同 seed 集逐策略配对。",
            "engine bot 基线读取完整状态（特权），仅作强度基线，不能作为 AZ 训练输入；"
            "被评策略/搜索的决策输入只有 observe(seat)+legal_mask。",
            "search_rust 默认叶评估器=heuristic 先验 + value 0；rollout 模式有已知"
            "off-policy 偏差（docs/AZ_PURE_SEARCH_TEST.md §3）。",
            "bot_prior/rollout 评估器是 game-aware 特权先验："
            "bot_prior 用引擎 bot 的单步动作做先验，刻意保留规则先验质量用于探索；"
            "只能作为搜索质量诊断/上限参考，不能当 AZ 训练输入（违反 D3）。",
            "初期脚手架：局数 10-20 级，统计噪声大（建议后续 500-2000 局 + bootstrap CI）。",
            "评测 seed 与自对弈/训练 seed 分离（评测 %d，自对弈 1e3/5e5 级）。" % args.seed,
        ],
    )
    report["timing"] = {"eval_seconds": eval_seconds,
                        "total_seconds": time.time() - t0,
                        "data_collection_enabled": bool(data_meta.get("enabled"))}
    errs = validate_eval_report(report)
    report["validation_errors"] = errs
    path = write_report(args.out, report)
    print("\n" + format_summary_table(report["policies"]), flush=True)
    print(f"[report] {path}", flush=True)
    if errs:
        print(f"[warn] 报告字段自检问题: {errs}", flush=True)
    print(f"[done] timing={json.dumps(report['timing'], ensure_ascii=False)}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
