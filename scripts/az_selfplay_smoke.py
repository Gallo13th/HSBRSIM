"""AlphaZero 初期自对弈/训练 smoke 入口（task-3）。

一条命令跑完：可选引擎 bot 冷启动(BC) → 自对弈采集轨迹 → 训练轻量策略/名次价值网络 →
保存 checkpoint → 策略评测（search-off / search-on vs 引擎 bot）→ 写 JSON 报告。

示例（远程 dev 机，Rust 主引擎）：

```bash
cd ~/projects/HSBRSIM
PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python \
  scripts/az_selfplay_smoke.py --policy search_rust --games 4 --search-sims 4 \
  --bootstrap-games 8 --epochs 2 --eval-games 5 --out runs/az_eval/selfplay_smoke
```

本脚本只写 ``--out`` 目录（默认 ``runs/az_eval/selfplay_smoke``），不修改任何既有模块。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train import (  # noqa: E402
    EvalConfig,
    SelfPlayConfig,
    engine_available,
    engine_info,
    evaluate_policy,
    make_policy,
)
from hsbg.az.train.data import AZDataset  # noqa: E402
from hsbg.az.train.evaluators import make_evaluator  # noqa: E402
from hsbg.az.train.model import (  # noqa: E402
    NetEvaluator,
    build_net,
    load_checkpoint,
    save_checkpoint,
)
from hsbg.az.train.report import build_train_report, write_report  # noqa: E402
from hsbg.az.train.selfplay import collect_selfplay  # noqa: E402
from hsbg.az.train.train_loop import evaluate_supervised, train_policy_value  # noqa: E402


def _repro_command(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "argv": list(sys.argv),
        "cwd": os.getcwd(),
        "python": sys.executable,
        "env_note": "PYTHONPATH 需包含 rust/python 与仓库根目录；需先构建安装 hsbg_engine",
    }


def _engine_bot_bootstrap(games: int, seed: int, sample_stride: int,
                          device: str, epochs: int, batch_size: int, lr: float,
                          max_samples: int, arch: str = "tiny") -> tuple[Optional[AZDataset], Optional[Any], Dict[str, Any]]:
    """引擎 bot 全座位 BC 冷启动数据 + 初始网络（AlphaZero 从零冷启动的常用做法）。

    说明：bot 读取完整状态（特权），这里只用它产生**演示数据**，训练好的网络本身
    推理只吃 observe（不把特权信息喂给网络），符合 D3 约束。
    """
    if games <= 0:
        return None, None, {"enabled": False}
    bot = make_policy("bot")
    cfg = SelfPlayConfig(games=int(games), seed=int(seed) + 700000, mode="game",
                         sample_stride=int(sample_stride), max_steps=20000)
    ds, meta = collect_selfplay(bot, cfg)
    meta = dict(meta)
    meta["kind"] = "engine_bot_bc_bootstrap"
    print(f"[bootstrap] bot data: {len(ds)} samples, {meta.get('games')} games, "
          f"{meta.get('elapsed_s', 0):.2f}s", flush=True)
    if len(ds) == 0:
        return ds, None, meta
    net = build_net(256, arch=arch)
    train = train_policy_value(net, ds, epochs=max(1, int(epochs)), batch_size=int(batch_size),
                               lr=float(lr), device=device, seed=0,
                               max_samples=int(max_samples))
    meta["train"] = {k: train[k] for k in ("samples", "seconds", "loss_first", "loss_last")}
    return ds, net, meta


def main() -> int:
    ap = argparse.ArgumentParser(description="AZ 初期自对弈/训练 smoke")
    ap.add_argument("--policy", default="search_rust",
                    help="自对弈策略：random|heuristic|net|search_rust|search_rust_rollout|"
                         "search_az")
    ap.add_argument("--games", type=int, default=4, help="自对弈局数")
    ap.add_argument("--mode", default="game", choices=["game", "batch"],
                    help="game=Game 逐步(可搜索)；batch=BatchEnv 8 座批量(仅纯策略)")
    ap.add_argument("--selfplay-seed", type=int, default=1000)
    ap.add_argument("--sample-stride", type=int, default=1)
    ap.add_argument("--search-sims", type=int, default=4)
    ap.add_argument("--search-temperature", type=float, default=1.0,
                    help="自对弈数据生成建议 1.0（探索）；评测用 <=0 = argmax")
    ap.add_argument("--search-det", type=int, default=1, help="search_az 的 determinizations")
    ap.add_argument("--search-backend", default="rust", choices=["rust", "az"])
    ap.add_argument("--evaluator", default="heuristic",
                    choices=["heuristic", "uniform", "net", "bot_prior", "rollout"],
                    help="搜索叶评估器；net 需要 --net-checkpoint 或 --bootstrap-games；"
                         "bot_prior/rollout 为 game-aware（特权/截断）诊断先验")
    ap.add_argument("--bot-prior-blend", type=float, default=0.75)
    ap.add_argument("--rollout-horizon", type=int, default=8)
    ap.add_argument("--search-engine-backend", default="auto",
                    choices=["auto", "rust", "python"])
    ap.add_argument("--net-checkpoint", default="", help="已有网络 checkpoint（跳过冷启动训练）")
    ap.add_argument("--bootstrap-games", type=int, default=8,
                    help="引擎 bot 全座位 BC 冷启动局数（0=关闭）")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--max-train-samples", type=int, default=20000)
    ap.add_argument("--arch", default="tiny", choices=["tiny", "entity", "entity18m"],
                    help="网络结构：tiny=MLP；entity=AutoTavern 风格实体 Transformer")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--eval-games", type=int, default=5, help="训练后 net(search-off) vs bot 局数")
    ap.add_argument("--eval-search-games", type=int, default=0,
                    help=">0 时额外评 search_rust(net evaluator, search-on) vs bot")
    ap.add_argument("--eval-seed", type=int, default=80000)
    ap.add_argument("--out", default="runs/az_eval/selfplay_smoke")
    args = ap.parse_args()

    if not engine_available():
        print("[error] hsbg_engine 不可用：需要 Rust 主引擎构建（cd rust && pip install -e .）",
              file=sys.stderr)
        return 2
    os.makedirs(args.out, exist_ok=True)
    t_start = time.time()
    eng = engine_info()
    torch_seed = 0
    np.random.seed(torch_seed)
    print(f"[engine] {json.dumps(eng, ensure_ascii=False)}", flush=True)

    # ── 1) 叶评估器：net（BC 冷启动/checkpoint）或 game-aware 诊断先验 ──
    bootstrap_ds: Optional[AZDataset] = None
    net = None
    bootstrap_meta: Dict[str, Any] = {"enabled": False}
    if args.evaluator == "bot_prior":
        from hsbg.az.policy import BotPriorEvaluator

        evaluator = BotPriorEvaluator(blend=float(args.bot_prior_blend))
        bootstrap_meta = {"enabled": False, "evaluator": "bot_prior",
                          "privileged": True,
                          "note": "bot 单步动作作为搜索先验（读取完整状态），仅诊断用"}
        print("[evaluator] bot_prior（特权先验，仅用于搜索质量诊断，不是 AZ 训练输入）",
              flush=True)
    elif args.evaluator == "rollout":
        from hsbg.az.policy import RolloutEvaluator

        evaluator = RolloutEvaluator(horizon=int(args.rollout_horizon))
        bootstrap_meta = {"enabled": False, "evaluator": "rollout"}
        print("[evaluator] rollout（截断 rollout 叶价值）", flush=True)
    elif args.net_checkpoint:
        net, ckpt_meta = load_checkpoint(args.net_checkpoint, device=args.device)
        evaluator = NetEvaluator(net, device=args.device,
                                 norm_mean=ckpt_meta.get("norm_mean"),
                                 norm_std=ckpt_meta.get("norm_std"))
        bootstrap_meta = {"enabled": True, "checkpoint": args.net_checkpoint,
                          "from_checkpoint": True}
        print(f"[net] 从 checkpoint 加载: {args.net_checkpoint}", flush=True)
    else:
        bootstrap_ds, net, bootstrap_meta = _engine_bot_bootstrap(
            args.bootstrap_games, args.selfplay_seed, args.sample_stride,
            args.device, args.epochs, args.batch_size, args.lr, args.max_train_samples,
            arch=args.arch)
        evaluator = (NetEvaluator(net, device=args.device) if net is not None
                     else make_evaluator("heuristic"))

    # ── 2) 自对弈采集轨迹 ──
    policy_kwargs: Dict[str, Any] = {"seed": args.selfplay_seed + 900000}
    if args.policy.startswith("search_rust") or args.policy in ("rust", "mcts_rust"):
        policy_kwargs.update(simulations=args.search_sims,
                             temperature=float(args.search_temperature),
                             evaluator=evaluator, dirichlet_epsilon=0.0)
        if args.policy in ("search_rust_rollout", "rollout"):
            policy_kwargs.pop("evaluator", None)
    elif args.policy in ("search_az", "az", "mcts_az"):
        engine_backend = args.search_engine_backend
        if getattr(evaluator, "accepts_game", False) and engine_backend == "auto":
            engine_backend = "python"
        policy_kwargs.update(simulations=args.search_sims,
                             temperature=float(args.search_temperature),
                             determinizations=args.search_det,
                             evaluator=evaluator, engine_backend=engine_backend)
    elif args.policy in ("net", "network"):
        if evaluator is None or getattr(evaluator, "accepts_game", False):
            print("[error] --policy net 需要 net 评估器（--net-checkpoint 或 --bootstrap-games>0）",
                  file=sys.stderr)
            return 2
        policy_kwargs = {"evaluator": evaluator}
    if getattr(evaluator, "accepts_game", False) and args.policy not in (
            "search_az", "az", "mcts_az"):
        print("[error] game-aware 先验（bot_prior/rollout）只能配 --policy search_az "
              "--search-engine-backend python", file=sys.stderr)
        return 2
    pol = make_policy(args.policy, **policy_kwargs)
    mode = args.mode
    if mode == "batch" and not hasattr(pol, "act_batch"):
        print(f"[warn] 策略 {args.policy} 不支持 act_batch，退回 game 模式", flush=True)
        mode = "game"
    cfg = SelfPlayConfig(games=int(args.games), seed=int(args.selfplay_seed), mode=mode,
                         n_games=1, sample_stride=int(args.sample_stride),
                         max_steps=20000)
    t_collect = time.time()
    dataset, collect_meta = collect_selfplay(pol, cfg)
    collect_meta["seconds"] = time.time() - t_collect
    data_quality = dataset.quality_metrics()
    print(f"[selfplay] {json.dumps({k: collect_meta.get(k) for k in ('mode', 'games', 'samples', 'decisions', 'illegal_actions', 'truncated_games', 'elapsed_s', 'games_per_s')}, ensure_ascii=False)}",
          flush=True)
    print(f"[data-quality] {json.dumps(data_quality, ensure_ascii=False)[:600]}", flush=True)
    errs = dataset.validate()
    if errs:
        print(f"[warn] 数据集自检问题: {errs}", flush=True)
    data_path = os.path.join(args.out, "data.npz")
    dataset.save(data_path)
    print(f"[data] {len(dataset)} samples -> {data_path}", flush=True)

    # ── 3) 训练（搜索数据 + 可选冷启动数据）──
    train_ds = dataset if bootstrap_ds is None else AZDataset.concat([bootstrap_ds, dataset])
    if net is None:
        net = build_net(256, arch=arch)
    t_train = time.time()
    train_meta = train_policy_value(
        net, train_ds, epochs=int(args.epochs), batch_size=int(args.batch_size),
        lr=float(args.lr), device=args.device, seed=0,
        max_samples=int(args.max_train_samples))
    train_meta["seconds"] = time.time() - t_train
    print(f"[train] loss {train_meta['loss_first']:.4f} -> {train_meta['loss_last']:.4f} "
          f"| {train_meta['samples']} samples, {train_meta['samples_per_s']:.0f} samples/s, "
          f"{train_meta['seconds']:.2f}s", flush=True)

    # ── 4) 监督评估 + checkpoint ──
    supervised = evaluate_supervised(net, dataset,
                                     norm_mean=train_meta["norm_mean"],
                                     norm_std=train_meta["norm_std"], device=args.device)
    print(f"[supervised] {json.dumps(supervised, ensure_ascii=False)}", flush=True)
    ckpt_path = os.path.join(args.out, "model.pt")
    save_checkpoint(net, ckpt_path, meta={
        "hidden": 256, "epochs": int(args.epochs), "samples": int(train_meta["samples"]),
        "policy": args.policy, "search_sims": int(args.search_sims),
        "data_version": eng.get("data_version"), "engine_version": eng.get("engine_version"),
        "collect": {k: collect_meta.get(k) for k in
                    ("mode", "games", "samples", "decisions", "policy")},
        "repro": _repro_command(args),
    }, norm_mean=train_meta["norm_mean"], norm_std=train_meta["norm_std"])
    print(f"[ckpt] {ckpt_path}", flush=True)

    # ── 5) 训练后评测（search-off net vs engine bot；可选 search-on）──
    net_eval = NetEvaluator(net, device=args.device, norm_mean=train_meta["norm_mean"],
                            norm_std=train_meta["norm_std"])
    eval_meta: Dict[str, Any] = {}
    if int(args.eval_games) > 0:
        net_pol = make_policy("net", evaluator=net_eval)
        cfg_net = EvalConfig(games=int(args.eval_games), seed=int(args.eval_seed))
        res_net = evaluate_policy(net_pol, cfg_net)
        bot_pol = make_policy("bot")
        res_bot = evaluate_policy(bot_pol, EvalConfig(games=int(args.eval_games),
                                                      seed=int(args.eval_seed)))
        eval_meta["net_search_off"] = res_net
        eval_meta["engine_bot_baseline"] = res_bot
        print(f"[eval] net(search-off): mean_rank={res_net['mean_rank']} "
              f"top4={res_net['top4_rate']} | bot: mean_rank={res_bot['mean_rank']}",
              flush=True)
    if int(args.eval_search_games) > 0:
        from hsbg.az.train.policies import RustMCTSPolicy

        search_pol = RustMCTSPolicy(simulations=max(2, int(args.search_sims)),
                                    temperature=0.0,
                                    seed=int(args.eval_seed) + 500, evaluator=net_eval,
                                    dirichlet_epsilon=0.0)
        res_search = evaluate_policy(search_pol, EvalConfig(games=int(args.eval_search_games),
                                                            seed=int(args.eval_seed)))
        eval_meta["net_search_on"] = res_search
        print(f"[eval] search-on(net prior): mean_rank={res_search['mean_rank']} "
              f"top4={res_search['top4_rate']}", flush=True)

    # ── 6) 报告 ──
    notes = [
        "初期 smoke：只证明管线可运行 + 数据质量字段；不追求棋力。",
        f"自对弈策略={args.policy}，搜索 sims={args.search_sims}，"
        f"叶评估器={args.evaluator}，模式={mode}。",
        "BC 冷启动使用引擎 bot（特权）产生演示数据；网络推理只用 observe（D3 约束）。",
        "搜索 rollout 模式存在已知 off-policy 价值偏差，见 docs/AZ_PURE_SEARCH_TEST.md §3。",
    ]
    if getattr(evaluator, "accepts_game", False):
        notes.append(
            "⚠ 本次叶评估器是 game-aware 特权先验（bot 单步动作/截断 rollout）："
            "生成的 π 目标含隐藏信息，只能用于搜索质量诊断，不能当作生产训练数据。")
    report = build_train_report(
        engine=eng,
        collect=collect_meta,
        data_quality=data_quality,
        train={k: v for k, v in train_meta.items() if k not in ("norm_mean", "norm_std")},
        supervised=supervised,
        checkpoint=ckpt_path,
        eval_search=eval_meta,
        repro=_repro_command(args),
        notes=notes,
    )
    report["bootstrap"] = bootstrap_meta
    report["total_seconds"] = time.time() - t_start
    report_path = os.path.join(args.out, "report.json")
    write_report(report_path, report)
    print(f"[report] {report_path}", flush=True)
    print("[done] " + json.dumps({
        "samples": len(dataset), "train_loss": [train_meta["loss_first"],
                                                train_meta["loss_last"]],
        "value_rank_corr": supervised.get("value_rank_corr"),
        "policy_top1_agreement": supervised.get("policy_top1_agreement"),
        "total_seconds": round(report["total_seconds"], 2),
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
