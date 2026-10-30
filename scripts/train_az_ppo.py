"""MCTS 引导的 PPO 训练入口（不完全信息 MCTS + 自对弈 + PPO）。

流程（一条命令闭环）::

    不完全信息 MCTS 自对弈采集（8 座 或 1 学习座 vs 引擎 bot）
      -> PPO 更新（clip / GAE / entropy / KL 早停 + α·CE(π_MCTS) 辅助目标）
      -> 固定 seed 评测（复用 hsbg.az.train.evaluate.evaluate_policy）
      -> 保存 checkpoint + JSON 报告

**这是"MCTS 引导的 PPO"，不是纯 AlphaZero CE**：主损失是 PPO clip surrogate；MCTS
visit π 只作为 ``--pi-coef``（α）权重的辅助交叉熵目标。行为动作默认由网络 masked
softmax 采样（严格 on-policy），也可切到 MCTS/混合行为（见 ``--behavior``）。

示例（远程 dev 机，CPU smoke；entity 正式训练把 --arch 换成 entity 并加大 --sims）::

    cd ~/projects/HSBRSIM
    PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python \
      scripts/train_az_ppo.py --games 1 --epochs 1 --arch tiny --sims 4 \
      --eval-games 1 --out runs/az_ppo/smoke

    # 只采集轨迹（不更新），产出 ppo_batch.npz + report.json
    ... scripts/train_az_ppo.py --games 2 --collect-only --out runs/az_ppo/collect

无 ``hsbg_engine`` 时给出清晰错误并返回 2；本脚本只写 ``--out`` 目录。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import (  # noqa: E402
    engine_available,
    engine_info,
    to_jsonable,
)
from hsbg.az.train.evaluate import EvalConfig, evaluate_policy  # noqa: E402
from hsbg.az.train.model import build_net, load_checkpoint, save_checkpoint  # noqa: E402
from hsbg.az.train.policies import make_policy  # noqa: E402
from hsbg.az.train.ppo import (  # noqa: E402
    CollectConfig,
    PPOConfig,
    PPOEvaluator,
    PPOGreedyPolicy,
    collect_ppo_batch,
    torch_available,
    train_ppo,
)
from hsbg.az.train.report import write_report  # noqa: E402
from hsbg.az.train.seq_aux import SeqCoefSchedule  # noqa: E402

SCHEMA = "hsbg.az.ppo_train/v1"


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="MCTS 引导的 PPO 训练（不完全信息 MCTS + 自对弈 + PPO）")
    # 主参数
    ap.add_argument("--games", type=int, default=2, help="自对弈局数（采集）")
    ap.add_argument("--epochs", type=int, default=2, help="PPO 训练 epoch 数")
    ap.add_argument("--arch", default="tiny", choices=["tiny", "entity", "entity18m"],
                    help="网络结构：tiny=MLP（快）；entity=AutoTavern 实体 Transformer")
    ap.add_argument("--device", default="cpu", help="torch 设备（默认 cpu）")
    ap.add_argument("--out", default="runs/az_ppo/ppo_smoke", help="输出目录")
    ap.add_argument("--seed", type=int, default=0, help="采集/训练随机种子")
    # MCTS 采集
    ap.add_argument("--sims", type=int, default=8,
                    help="每次决策的 MCTS 模拟数（0=关闭搜索，退化为纯网络自对弈）")
    ap.add_argument("--determinizations", type=int, default=1,
                    help="PIMC 世界数 W（determinizations）")
    ap.add_argument("--c-puct", type=float, default=1.5, help="PUCT 探索常数")
    ap.add_argument("--search-temperature", type=float, default=1.0,
                    help="MCTS visit π 的温度（采集建议 1.0）")
    ap.add_argument("--dirichlet-alpha", type=float, default=0.3)
    ap.add_argument("--dirichlet-epsilon", type=float, default=0.0,
                    help="根 Dirichlet 噪声比例（自对弈探索可设 0.25）")
    ap.add_argument("--engine-backend", default="auto", choices=["auto", "rust", "python"],
                    help="hsbg.az.search 的搜索后端")
    ap.add_argument("--opponent", default="self", choices=["self", "bot"],
                    help="self=8 座自对弈；bot=1 学习座 vs 7 引擎 bot")
    ap.add_argument("--learner-seat", type=int, default=0,
                    help="--opponent bot 时学习座位号")
    ap.add_argument("--behavior", default="net", choices=["net", "mcts", "mixed"],
                    help="行为动作来源：net=网络采样（严格 on-policy）；mcts=visit π 采样；"
                         "mixed=(1-ε)π_MCTS+ε π_net")
    ap.add_argument("--temperature", type=float, default=1.0,
                    help="网络行为采样温度（logits / τ）")
    ap.add_argument("--pi-epsilon", type=float, default=0.0,
                    help="behavior=mixed 时网络概率权重 ε")
    ap.add_argument("--step-penalty", type=float, default=0.0,
                    help="每决策小 step penalty（进入 reward）")
    ap.add_argument("--max-steps", type=int, default=20000, help="单局步数守卫")
    ap.add_argument("--max-actions-per-turn", type=int, default=40,
                    help="单座位单回合动作上限（超过且 EndTurn 合法则强制结束回合；"
                         "0=关闭。未训练网络防 Play/Cancel 死循环）")
    ap.add_argument("--move-guard", type=int, default=0, choices=[0, 1],
                    help="1=换位去抖守卫（默认 0=关闭，逐位等价；见 docs/MOVE_GUARD.md）")
    ap.add_argument("--move-cap", type=int, default=3,
                    help="每回合换位次数上限（默认 3；0=本回合禁止换位）")
    ap.add_argument("--move-repeat-limit", type=int, default=2,
                    help="同一 (from,to) 本回合出现 >=N 次后屏蔽（默认 2）")
    # PPO 超参
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--clip", type=float, default=0.2, help="PPO clip ε")
    ap.add_argument("--minibatch", type=int, default=64)
    ap.add_argument("--gamma", type=float, default=1.0, help="折扣因子（终局效用通常 1.0）")
    ap.add_argument("--lam", type=float, default=0.95, help="GAE λ")
    ap.add_argument("--entropy-coef", type=float, default=0.01)
    ap.add_argument("--value-coef", type=float, default=0.5)
    ap.add_argument("--pi-coef", type=float, default=0.5,
                    help="MCTS visit π 辅助 CE 权重 α（0=关闭，退化为纯 PPO）")
    ap.add_argument("--seq-coef", type=float, default=0.0,
                    help="动作序列辅助头（该 seat 在本 turn 内动作 multi-hot 的 BCE）权重；"
                         "0=关闭（默认）。见 docs/ACTION_SEQUENCE_AUX.md")
    ap.add_argument("--seq-coef-ramp", default="",
                    help='按 decisions 比例的线性 ramp（如 "0.02@0,0.05@0.5"）；'
                         "本入口只跑一轮，ramp 进度取 0")
    ap.add_argument("--value-loss", default="rank", choices=["rank", "mse"],
                    help="价值损失：rank=名次 CE；mse=value MSE（critic=E[u(rank)]）")
    ap.add_argument("--value-head-coef", type=float, default=0.0,
                    help="entity 标量 value 头辅助 MSE 权重（tiny 无此头，忽略）")
    ap.add_argument("--target-kl", type=float, default=0.02,
                    help="目标 KL（>0 且开启早停时生效）")
    ap.add_argument("--no-kl-early-stop", action="store_true",
                    help="关闭 KL 早停")
    ap.add_argument("--max-grad-norm", type=float, default=0.5)
    ap.add_argument("--max-samples", type=int, default=0,
                    help="PPO 每轮最多使用的样本数（0=全部）")
    ap.add_argument("--log-every", type=int, default=0, help="每 N 个 minibatch 打印")
    ap.add_argument("--hidden", type=int, default=256, help="tiny 网络隐藏维")
    # 评测 / 输出
    ap.add_argument("--eval-games", type=int, default=2,
                    help="训练后固定 seed 评测局数（0=跳过）")
    ap.add_argument("--eval-seed", type=int, default=90000, help="评测固定 seed 起点")
    ap.add_argument("--baseline-games", type=int, default=0,
                    help=">0 时同 seed 跑引擎 bot 基线并写 delta")
    ap.add_argument("--checkpoint", default="", help="续训 checkpoint（可选）")
    ap.add_argument("--collect-only", action="store_true",
                    help="只采集轨迹并写 ppo_batch.npz + report.json，不做 PPO 更新")
    return ap.parse_args()


def _repro_command(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "argv": list(sys.argv),
        "cwd": os.getcwd(),
        "python": sys.executable,
        "env_note": "PYTHONPATH 需包含 rust/python 与仓库根目录；需安装 hsbg_engine 与 torch",
        "args": to_jsonable(vars(args)),
    }


def _eval_summary(res: Dict[str, Any]) -> Dict[str, Any]:
    """报告里去掉大数组（examples）。"""
    out = dict(res)
    out.pop("examples", None)
    return out


def main() -> int:
    args = _parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用：需要先构建安装 Rust 主引擎 "
              "(`cd rust && python -m pip install -e .`)，见 docs/RUST_ENGINE.md",
              file=sys.stderr)
        return 2
    if not torch_available():
        print("[error] torch 不可用：PPO 训练需要 torch（`pip install torch`）",
              file=sys.stderr)
        return 2
    if int(args.games) < 1:
        print("[error] --games 必须 >= 1", file=sys.stderr)
        return 2
    if int(args.epochs) < 1 and not args.collect_only:
        print("[error] --epochs 必须 >= 1（--collect-only 时忽略）", file=sys.stderr)
        return 2
    if int(args.move_cap) < 0:
        print("[error] --move-cap 必须 >= 0", file=sys.stderr)
        return 2
    if int(args.move_repeat_limit) < 1:
        print("[error] --move-repeat-limit 必须 >= 1", file=sys.stderr)
        return 2

    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        print(f"[error] import torch 失败: {exc!r}", file=sys.stderr)
        return 2
    # 动作序列辅助任务（默认关闭）：系数 = ramp 在进度 0 处的值（无 ramp 时 = --seq-coef）
    try:
        seq_schedule = SeqCoefSchedule.from_spec(
            base_coef=float(args.seq_coef), spec=str(args.seq_coef_ramp),
            total_decisions=1.0)  # 单轮入口：ramp 进度恒为 0
    except ValueError as exc:
        print(f"[error] --seq-coef-ramp 非法: {exc}", file=sys.stderr)
        return 2
    seq_enabled = bool(seq_schedule.enabled)
    seq_coef = float(seq_schedule.coef(0)) if seq_enabled else 0.0
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % (2 ** 32))
    os.makedirs(args.out, exist_ok=True)
    t_start = time.time()
    eng = engine_info()
    print(f"[engine] {json.dumps(eng, ensure_ascii=False)}", flush=True)

    # ── 1) 网络（可选从 checkpoint 续训）──
    norm_mean: Optional[np.ndarray] = None
    norm_std: Optional[np.ndarray] = None
    if args.checkpoint:
        model, ckpt_meta = load_checkpoint(args.checkpoint, device=args.device)
        arch = str(ckpt_meta.get("arch", args.arch))
        norm_mean = ckpt_meta.get("norm_mean")
        norm_std = ckpt_meta.get("norm_std")
        print(f"[net] 从 checkpoint 续训: {args.checkpoint} (arch={arch})", flush=True)
        if seq_enabled and getattr(model, "seq_head", None) is None:
            print("[warn] checkpoint 没有动作序列辅助头：本次关闭 seq 辅助任务", flush=True)
            seq_enabled = False
            seq_coef = 0.0
    else:
        model = build_net(int(args.hidden), arch=args.arch, seq_head=seq_enabled)
        arch = str(args.arch)
    model.to(torch.device(args.device))
    print(f"[net] arch={arch} params={sum(p.numel() for p in model.parameters()):,} "
          f"device={args.device}", flush=True)
    if seq_enabled:
        print(f"[seq] 动作序列辅助头已启用 coef={seq_coef:.4g}"
              f" ramp={args.seq_coef_ramp or '(none)'}", flush=True)

    # ── 2) 搜索（MCTS visit π 采集 / 辅助目标）──
    search_fn = None
    search_cfg = None
    behavior = str(args.behavior)
    if int(args.sims) > 0:
        try:
            from hsbg.az import SearchConfig, search as az_search
        except Exception as exc:  # noqa: BLE001
            print(f"[error] hsbg.az 搜索原型不可用: {exc!r}", file=sys.stderr)
            return 2
        search_cfg = SearchConfig(
            simulations=int(args.sims), determinizations=int(args.determinizations),
            c_puct=float(args.c_puct), temperature=float(args.search_temperature),
            dirichlet_alpha=float(args.dirichlet_alpha),
            dirichlet_epsilon=float(args.dirichlet_epsilon), seed=int(args.seed))
        search_fn = az_search
    elif behavior in ("mcts", "mixed"):
        print(f"[warn] --sims=0 时无法使用 {behavior} 行为，回退为 net", flush=True)
        behavior = "net"
    if search_fn is None and float(args.pi_coef) > 0.0:
        print("[warn] 未开启 MCTS（--sims 0），π 辅助 CE 目标为空（pi_coef 无效）",
              flush=True)

    # ── 3) MCTS 自对弈采集 ──
    c_cfg = CollectConfig(
        games=int(args.games), seed=int(args.seed) + 1000,
        max_steps=int(args.max_steps), opponent=str(args.opponent),
        learner_seat=int(args.learner_seat), behavior=behavior,
        temperature=float(args.temperature), pi_epsilon=float(args.pi_epsilon),
        step_penalty=float(args.step_penalty),
        max_actions_per_turn=int(args.max_actions_per_turn),
        move_guard=bool(int(args.move_guard)),
        move_cap=int(args.move_cap),
        move_repeat_limit=int(args.move_repeat_limit),
        seq_aux=bool(seq_enabled))
    evaluator = PPOEvaluator(model, device=args.device,
                             norm_mean=norm_mean, norm_std=norm_std)
    t_collect = time.time()
    try:
        batch, collect_meta = collect_ppo_batch(
            model, c_cfg, search_fn=search_fn, search_config=search_cfg,
            eval_fn=evaluator, engine_backend=str(args.engine_backend),
            device=str(args.device), seed=int(args.seed) + 1000,
            gamma=float(args.gamma), lam=float(args.lam),
            step_penalty=float(args.step_penalty),
            norm_mean=norm_mean, norm_std=norm_std, progress=True)
    except (ValueError, RuntimeError) as exc:
        print(f"[error] 采集失败: {exc}", file=sys.stderr)
        return 3
    collect_meta = dict(collect_meta)
    collect_meta["seconds"] = time.time() - t_collect
    errs = batch.validate()
    if errs:
        print(f"[error] PPO 批次校验失败: {errs}", file=sys.stderr)
        return 3
    data_summary = batch.summary()
    print(f"[collect] {json.dumps(data_summary, ensure_ascii=False)}", flush=True)
    data_path = os.path.join(args.out, "ppo_batch.npz")
    batch.save(data_path)
    print(f"[data] {len(batch)} 决策样本 -> {data_path}", flush=True)

    if args.collect_only:
        report = {
            "schema": SCHEMA,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "mode": "collect_only",
            "engine": eng,
            "collect": collect_meta,
            "data": data_summary,
            "batch_path": data_path,
            "repro": _repro_command(args),
            "notes": ["只采集轨迹：未做 PPO 更新。",
                      "轨迹来自不完全信息 MCTS 自对弈；π_MCTS 已存入 target_pi。"],
            "total_seconds": time.time() - t_start,
        }
        report_path = os.path.join(args.out, "report.json")
        write_report(report_path, report)
        print(f"[report] {report_path}", flush=True)
        print("[done] collect-only", flush=True)
        return 0

    # ── 4) PPO 更新 ──
    p_cfg = PPOConfig(
        epochs=int(args.epochs), minibatch=int(args.minibatch), lr=float(args.lr),
        clip=float(args.clip), gamma=float(args.gamma), lam=float(args.lam),
        entropy_coef=float(args.entropy_coef), value_coef=float(args.value_coef),
        pi_coef=float(args.pi_coef), value_loss=str(args.value_loss),
        value_head_coef=float(args.value_head_coef), target_kl=float(args.target_kl),
        kl_early_stop=not bool(args.no_kl_early_stop),
        normalize_advantage=True, max_grad_norm=float(args.max_grad_norm),
        device=str(args.device), seed=int(args.seed),
        max_samples=(None if int(args.max_samples) <= 0 else int(args.max_samples)),
        log_every=int(args.log_every),
        seq_coef=(seq_coef if seq_enabled else 0.0),
        seq_coef_ramp=(str(args.seq_coef_ramp) if seq_enabled else ""))
    t_train = time.time()
    train_stats = train_ppo(model, batch, p_cfg)
    train_stats["seconds_wall"] = time.time() - t_train
    print(f"[ppo] updates={train_stats['updates']} samples={train_stats['samples']} "
          f"elapsed={train_stats['seconds']:.2f}s "
          f"stopped_early={train_stats['stopped_early']}", flush=True)

    # ── 5) checkpoint ──
    ckpt_meta: Dict[str, Any] = {
        "arch": arch, "hidden": int(args.hidden),
        "samples": int(len(batch)), "epochs": int(args.epochs),
        "seed": int(args.seed), "behavior": behavior,
        "sims": int(args.sims), "determinizations": int(args.determinizations),
        "clip": float(args.clip), "lr": float(args.lr),
        "pi_coef": float(args.pi_coef), "value_loss": str(args.value_loss),
        "data_version": eng.get("data_version"),
        "engine_version": eng.get("engine_version"),
        "repro": _repro_command(args),
    }
    if seq_enabled:
        ckpt_meta["seq_coef"] = float(seq_coef)
        ckpt_meta["seq_coef_ramp"] = str(args.seq_coef_ramp)
    ckpt_path = os.path.join(args.out, "model.pt")
    save_checkpoint(model, ckpt_path, meta=ckpt_meta,
                    norm_mean=norm_mean, norm_std=norm_std)
    print(f"[ckpt] {ckpt_path}", flush=True)

    # ── 6) 固定 seed 评测（search-off net vs 引擎 bot）──
    eval_meta: Dict[str, Any] = {}
    if int(args.eval_games) > 0:
        eval_ev = PPOEvaluator(model, device=args.device,
                               norm_mean=norm_mean, norm_std=norm_std)
        net_pol = PPOGreedyPolicy(eval_ev,
                                  max_actions_per_turn=int(args.max_actions_per_turn))
        res_net = evaluate_policy(
            net_pol, EvalConfig(games=int(args.eval_games), seed=int(args.eval_seed),
                                max_steps=int(args.max_steps)))
        eval_meta["ppo_net"] = _eval_summary(res_net)
        eval_meta["ppo_net_forced_end_turns"] = int(getattr(net_pol, "forced_actions", 0))
        print(f"[eval] ppo_net: mean_rank={res_net['mean_rank']} "
              f"top4={res_net['top4_rate']} win={res_net['win_rate']} "
              f"legal={res_net['legal_action_rate']:.4f}", flush=True)
        if int(args.baseline_games) > 0:
            bot_pol = make_policy("bot")
            res_bot = evaluate_policy(
                bot_pol, EvalConfig(games=int(args.baseline_games), seed=int(args.eval_seed),
                                    max_steps=int(args.max_steps)))
            eval_meta["engine_bot"] = _eval_summary(res_bot)
            eval_meta["delta"] = {
                "mean_rank": (None if res_net["mean_rank"] is None
                              or res_bot["mean_rank"] is None
                              else float(res_net["mean_rank"] - res_bot["mean_rank"])),
                "top4_rate": (None if res_net["top4_rate"] is None
                              or res_bot["top4_rate"] is None
                              else float(res_net["top4_rate"] - res_bot["top4_rate"])),
                "mean_utility": (None if res_net["mean_utility"] is None
                                 or res_bot["mean_utility"] is None
                                 else float(res_net["mean_utility"] - res_bot["mean_utility"])),
            }
            print(f"[eval] engine_bot: mean_rank={res_bot['mean_rank']}", flush=True)

    # ── 7) JSON 报告 ──
    notes = [
        "本阶段是 MCTS 引导的 PPO（主损失=PPO clip），不是纯 AlphaZero CE；"
        "MCTS visit π 仅作 --pi-coef 权重的辅助交叉熵目标。",
        f"行为策略 behavior={behavior}；"
        + ("严格 on-policy：old_logprob 为网络 masked softmax 下动作 log 概率。"
           if behavior == "net" else
           "行为策略=MCTS/混合：old_logprob 为实际行为分布下动作 log 概率"
           "（PPO ratio 分母非网络自身，属搜索行为的重要性修正，训练更激进）。"),
        "非法动作由 masked softmax 杜绝（评估 legal_action_rate 应为 1.0）。",
        "截断局（rank=0）整局丢弃，不做 bootstrap。",
    ]
    if arch == "entity":
        notes.append("entity 网络每个叶评估是单样本 Transformer forward，MCTS 采集较慢；"
                     "smoke 建议 --sims 小、--games 1。")
    report = {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "mode": "ppo_train",
        "engine": eng,
        "config": {
            "arch": arch, "device": str(args.device), "seed": int(args.seed),
            "games": int(args.games), "epochs": int(args.epochs),
            "sims": int(args.sims), "determinizations": int(args.determinizations),
            "behavior": behavior, "opponent": str(args.opponent),
            "lr": float(args.lr), "clip": float(args.clip),
            "minibatch": int(args.minibatch), "gamma": float(args.gamma),
            "lam": float(args.lam), "pi_coef": float(args.pi_coef),
            "entropy_coef": float(args.entropy_coef), "value_coef": float(args.value_coef),
            "value_loss": str(args.value_loss), "target_kl": float(args.target_kl),
            "kl_early_stop": not bool(args.no_kl_early_stop),
        },
        "collect": {k: v for k, v in collect_meta.items() if k != "games_meta"},
        "data": data_summary,
        "ppo": train_stats,
        "checkpoint": ckpt_path,
        "batch_path": data_path,
        "eval": eval_meta,
        "repro": _repro_command(args),
        "notes": notes,
        "total_seconds": time.time() - t_start,
    }
    if seq_enabled:
        # 动作序列辅助任务：只在启用时写入 report（默认关闭时 report 与旧版一致）
        report["config"].update({"seq_coef": float(seq_coef),
                                 "seq_coef_ramp": str(args.seq_coef_ramp)})
        report["seq"] = {"coef": float(seq_coef),
                         "loss": float(train_stats.get("seq_loss", 0.0)),
                         "note": "turn 内动作 multi-hot 的 BCE；标签含本回合后续动作（见 "
                                 "docs/ACTION_SEQUENCE_AUX.md）"}
        notes.append("已开启动作序列辅助头（--seq-coef>0）：标签=该 seat 在本 turn 内"
                     "实际执行过的动作集合 multi-hot，仅作辅助正则；forced 样本不参与。")
    report_path = os.path.join(args.out, "report.json")
    write_report(report_path, report)
    print(f"[report] {report_path}", flush=True)
    final = {
        "samples": len(batch),
        "ppo_updates": train_stats["updates"],
        "ppo_final_total": (train_stats["epochs"][-1]["total"]
                            if train_stats["epochs"] else None),
        "mean_rank": (eval_meta.get("ppo_net") or {}).get("mean_rank"),
        "legal_action_rate": (eval_meta.get("ppo_net") or {}).get("legal_action_rate"),
        "total_seconds": round(report["total_seconds"], 2),
    }
    print("[done] " + json.dumps(to_jsonable(final), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
