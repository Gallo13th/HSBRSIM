#!/usr/bin/env python3
"""Entity PPO 训练入口（持久 trainer + 进程级 actor pool + 可选 double-buffer 流水线）。

三条执行模式：

1. **串行**（默认）：collect → update → 快照/日志，语义最简单；
2. **流水线**（`--pipeline 1`，需要 `--processes > 1`）：`collect(B_{k+1})` 与 `update(B_k)`
   并行；actor 用**版本化权重文件**（任务开始时按 `weights_version` 懒加载），因此一批数据
   始终由同一个版本采集 → 滞后恒为 1，可断言；
3. 多线程采集（`--workers > 1 --processes 1`）：老路径，保留兼容。

评测：`--eval-every-decisions N` 到点做评测；`--eval-async 1` 时评测交给独立子进程
（默认 `--eval-device cuda:4`），主循环不等待，结果由轻量线程追加到
`eval/history.json`；`--eval-async 0` 保持旧的同步阻塞行为。`--eval-panel {bot,human,both}`
决定跑哪个面板（默认 both；human=人类战团对手面板，新主指标，见 `docs/EVAL_PANELS.md`），
两个 panel 各起一个子进程、串行排队（并发上限仍为 1）。

日志：`history.jsonl`（逐 iteration 追加，O(1)；不再全量重写 `history.json`），
`summary.json` 只存聚合信息；`--trainer-state` 可精确续训。

超参照 `docs/MULTISTAGE_TRAINING.md` §12（AutoTavern 论文 Table 7 对齐）：
sims=0 / clip 0.2 / target KL 0.05 / λ=0.995 / entropy 0.002 / grad-clip 1.0 /
lr 6e-6→5e-6 / 有效 minibatch = minibatch × grad_accum（8192）/ KL anchor β=0.1 前 100 iter。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, engine_info, to_jsonable  # noqa: E402
from hsbg.az.train.mirror_snapshots import ramp_p  # noqa: E402
from hsbg.az.train.reward_shaping import (parse_tier_bonus,  # noqa: E402
                                          shaping_gamma_warning)
from hsbg.az.train.tier_target import parse_tier_target_table  # noqa: E402
from hsbg.az.train.model import (  # noqa: E402
    attach_bc_card_head,
    attach_move_head_split,
    attach_strength_head,
    bc_card_head_dim,
    build_net,
    load_checkpoint,
    save_checkpoint,
)
from hsbg.az.train.ppo import (  # noqa: E402
    CollectConfig,
    PPOConfig,
    PPOEvaluator,
    collect_ppo_batch,
    forward_model,
    masked_log_softmax_torch,
    split_model_outputs,
    torch_available,
)
from hsbg.az.train.ppo_trainer import PPOTrainer  # noqa: E402
from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator  # noqa: E402
from hsbg.az.train.parallel_collect import collect_ppo_batch_parallel  # noqa: E402
from hsbg.az.train.process_pool import ProcessActorPool  # noqa: E402
from hsbg.az.train.runlog import (append_record, read_run, slim_collect,  # noqa: E402
                                  write_header, write_summary)
from hsbg.az.train.seq_aux import SeqCoefSchedule  # noqa: E402
from hsbg.az.train.bc_aux import (  # noqa: E402
    bc_pool_summary,
    load_bc_samples,
    parse_bc_class_weights,
)
from hsbg.az.train.dpo_upgrade import (  # noqa: E402
    UpgradeSamples,
    dpo_pair_loss,
    load_upgrade_samples,
)
from scripts.async_eval import (AsyncEvalRunner, build_c0_cmd,  # noqa: E402
                                build_human_cmd, panels_from_spec,
                                parse_panel_result, write_json_atomic)


#: 期望梯度占比的参考量级：PPO total loss（value 项主导）。本 run 无历史时用 s9d 实测均值。
DPO_REF_TOTAL_LOSS = 0.77


def _ppo_total_ref(out_dir: str) -> tuple:
    """本 run 最近一次 PPO ``total`` loss（无历史时退回 s9d 量级常数）；返回 (值, 来源)。"""
    path = os.path.join(str(out_dir), "history.jsonl")
    try:
        last = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        if last:
            rec = json.loads(last)
            for e in reversed((rec.get("ppo") or {}).get("epochs") or []):
                if "total" in e:
                    return float(e["total"]), "本 run history"
    except Exception:  # noqa: BLE001 - 只是启动打印的参考值
        pass
    return float(DPO_REF_TOTAL_LOSS), "s9d 量级常数"


def _dpo_startup_probe(model, pool: "UpgradeSamples", *, beta: float,
                       device: str, n: int = 512) -> Dict[str, float]:
    """启动诊断：当前策略在 upgrade 池上的 DPO 初值/接受率（no_grad，不改权重）。"""
    import torch

    sel = np.arange(min(int(n), len(pool)), dtype=np.int64)
    sub = pool.take(sel)
    was_training = bool(model.training)
    model.eval()
    try:
        with torch.no_grad():
            loss, rate = dpo_pair_loss(model, sub, float(beta), device=str(device))
        return {"n": float(len(sub)), "loss": float(loss),
                "accept_rate": float(rate)}
    finally:
        model.train(was_training)


def _dpo_grad_ref(path: str = "runs/dpo_grad_probe.json"):
    """读离线梯度占比探针结果（``scripts/dpo_grad_probe.py``）；没有则 None。"""
    try:
        with open(str(path), encoding="utf-8") as f:
            data = json.load(f)
        share = float(data["share_per_coef"])       # coef=1 时 ‖g_dpo‖/‖g_ppo‖
        if not np.isfinite(share) or share <= 0.0:
            return None
        return {"path": str(path), "share_per_coef": share,
                "checkpoint": data.get("checkpoint")}
    except Exception:  # noqa: BLE001 - 诊断文件缺失/损坏不影响训练
        return None


def _gpu_used_mib() -> Dict[int, int]:
    """``nvidia-smi`` 查询每张 GPU 已用显存（MiB）；查询失败返回 {}（=不做剔除）。"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.used",
             "--format=csv,noheader,nounits"],
            text=True, timeout=10, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        return {}
    used: Dict[int, int] = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            used[int(parts[0])] = int(float(parts[1]))
        except ValueError:
            continue
    return used


def _atomic_torch_save(obj: Any, path: str) -> None:
    import torch
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Entity PPO（持久 trainer + 进程 pool + 流水线）")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--stop-at-decisions", type=float, default=0.0,
                    help="累计 learner decisions 达到该值后停止（0=不启用）；与 --minutes 取先到者")
    ap.add_argument("--iterations", type=int, default=0)
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity", "entity18m"])
    ap.add_argument("--move-head-split", type=int, default=0, choices=[0, 1],
                    help="1=Move 段（196..244）用有向双投影（move_from/move_to），"
                         "方向差不再只由 move_bias 决定；旧 checkpoint 自动只初始化新投影。"
                         "默认 0=保持对称实现（逐位兼容旧 ckpt）")
    ap.add_argument("--move-guard", type=int, default=0, choices=[0, 1],
                    help="1=换位去抖守卫：采样前屏蔽「逆换位 / 同动作超限 / 本回合换位"
                         "超 cap」的 Move 动作位（见 docs/MOVE_GUARD.md）。"
                         "默认 0=关闭（与旧路径逐位等价）")
    ap.add_argument("--move-cap", type=int, default=3,
                    help="每回合换位次数上限：>=cap 后屏蔽全部 Move（默认 3；0=本回合禁止换位）")
    ap.add_argument("--move-repeat-limit", type=int, default=2,
                    help="同一 (from,to) 本回合出现 >=N 次后屏蔽（默认 2；1=不允许重复）")
    # ── 流派（archetype）软偏置（默认关闭；见 docs/ARCHETYPE_BIAS.md）──
    ap.add_argument("--archetype-bias-coef", type=float, default=0.0,
                    help="流派软偏置系数：0=关闭（逐位等价旧路径）。对当前流派在当前 "
                         "turn 的偏好动作加 coef*相对增益 的 logit（只加不减、不屏蔽），"
                         "建议 0.5–2.0")
    ap.add_argument("--archetype-min-prob", type=float, default=0.6,
                    help="检测置信度门槛：max_prob >= 该值才偏置（低置信不偏置，默认 0.6）")
    ap.add_argument("--archetype-table", default="",
                    help="偏好表路径（空= data/archetype/archetype_table.json）")
    ap.add_argument("--archetype-model", default="",
                    help="分类器模型路径（空= data/archetype/archetype_model.npz）")
    ap.add_argument("--archetype-cache", type=int, default=0,
                    help="1=流派特征/分类走输入哈希缓存（输出逐位相同，但实测命中率≈0，"
                         "默认 0 关闭；见 docs/PERF_COLLECT.md）")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--sims", type=int, default=4)
    ap.add_argument("--determinizations", type=int, default=1)
    ap.add_argument("--opponent", default="bot", choices=["bot", "self", "weak"])
    ap.add_argument("--behavior", default="net", choices=["net", "mcts", "mixed"])
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--minibatch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lr-min-ratio", type=float, default=0.1)
    ap.add_argument("--max-updates", type=int, default=100000)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--target-kl", type=float, default=0.05)
    ap.add_argument("--lam", type=float, default=0.95,
                    help="GAE λ（与折扣 γ 无关；论文 0.995）")
    ap.add_argument("--gamma", type=float, default=1.0,
                    help="训练折扣 γ（默认 1.0：8 座单局终局效用；不是 GAE 的 λ）")
    ap.add_argument("--max-grad-norm", type=float, default=0.5,
                    help="梯度裁剪范数（论文 1.0）")
    ap.add_argument("--grad-accum", type=int, default=1,
                    help="梯度累积步数：有效 minibatch = minibatch * grad_accum（论文 8192）")
    ap.add_argument("--leaf-compile", type=int, default=0,
                    help="1=叶前向 torch.compile + TF32（实测 B=64 5.4→0.7 ms）")
    ap.add_argument("--leaf-amp", default="off", choices=["off", "bf16"],
                    help="采集/评测叶前向精度（bf16 实测 collect 约 -5%%）")
    ap.add_argument("--leaf-wait-ms", type=float, default=2.0,
                    help="批量叶服务器聚批等待（ms）；单客户端建议 0.1")
    ap.add_argument("--rc-threads", type=int, default=8,
                    help="Rust 采集器内部引擎线程数（BatchEnv threads）")
    ap.add_argument("--rust-collector", type=int, default=0,
                    help="1=Rust 全采集器（BatchEnv 驱动，记录打包在 Rust）")
    ap.add_argument("--library-pool", default="",
                    help="镜像对手库 JSONL（空=不用）；见 docs/LIBRARY_POOL_PLAN.md")
    ap.add_argument("--frozen-seats", type=int, default=0,
                    help="由冻结对手驱动的 bot 座位数（1–2 性价比最高；7=全部，慢 ~25x）")
    ap.add_argument("--frozen-opponent", default="",
                    help="冻结对手模型 checkpoint（空=引擎 bot）；bot 座位由它驱动（分裂模型/自对弈）")
    ap.add_argument("--trajectory-pool", default="",
                    help="对手场面轨迹库目录（空=不用）；见 docs/LIBRARY_POOL_PLAN.md")
    ap.add_argument("--trajectory-p", type=float, default=0.0,
                    help="每局被轨迹镜像替换的概率（建议 0.1 起）")
    ap.add_argument("--mirror-snaps", default="",
                    help="回合末场面快照库目录（snap_*.json.gz；空=不用）；见 "
                         "docs/MIRROR_SNAPSHOT_DESIGN.md")
    ap.add_argument("--mirror-seats", type=int, default=0,
                    help="回合末快照镜像的座位数：给 seat 1..N 注入（0=关闭，最大 7）")
    ap.add_argument("--mirror-p", type=float, default=0.0,
                    help="每座位每回合注入快照的概率（默认 0=关闭，零影响）")
    ap.add_argument("--mirror-sample", "--sample", dest="mirror_sample", default="p50",
                    choices=["p50", "p75", "p90", "max", "strong", "weak", "random"],
                    help="快照桶内采样：p50/p75/p90=强度分位课程（默认），max/strong=旧上限")
    ap.add_argument("--mirror-p-ramp", default="",
                    help="线性 p ramp，如 0.1@0,0.25@0.3,0.25@1.0（x 与 iteration 同单位）；"
                         "空=用固定 --mirror-p")
    ap.add_argument("--mirror-seat-random", type=int, default=0,
                    help="1=每回合从全部非 learner 座位随机抽 --mirror-seats 个（课程模式）")
    ap.add_argument("--human-boards", default="",
                    help="人类战团（board-only）JSONL（默认 "
                         "data/real_library/library_real_degraded.jsonl；空=不用）；见 "
                         "docs/HUMAN_BOARD_OPPONENT.md")
    ap.add_argument("--human-board-p", type=float, default=0.0,
                    help="每个候选座位每回合注入人类战团的概率（默认 0=关闭，零影响）")
    ap.add_argument("--human-board-seats", type=int, default=2,
                    help="每回合从全部非 learner 座位里随机抽几个座位注入（默认 2）")
    ap.add_argument("--human-board-sample", default="auto",
                    choices=["auto", "p50", "p75", "p90", "max"],
                    help="人类战团桶内分位：auto=按 turn 走难度曲线（t<=8 p50 / 9..12 p75 "
                         "/ t>=13 p90，默认）")
    ap.add_argument("--human-board-set-tier", type=int, default=1,
                    help="1=同时写入按 turn 派生的酒馆等级（人类数据没有 tier 字段；默认 1）")
    ap.add_argument("--human-board-fidelity", default="board",
                    choices=["board", "hand", "full"],
                    help="人类战团注入保真度：board=board-only（默认，逐位等价现状）；"
                         "hand=board+手牌；full=board+hand+可推断 counters"
                         "（关键词位/金身/圣盾层数/tavern tier）。hand/full 需要 "
                         "data/real_library/library_real_quasi_full.jsonl"
                         "（scripts/build_fidelity_library.py 生成）；见 "
                         "docs/FIDELITY_INJECTION.md")
    ap.add_argument("--human-board-fast-inject", type=int, default=0,
                    help="1=人类战团注入走快速路径（payload 注入视图缓存 + orjson + "
                         "ended 位字符串替换）；**与默认路径逐位等价**（同 seed 动作序列/"
                         "状态 JSON 完全相同），实测采集侧 Python 成本降约四成。默认 0=旧路径")
    # ---- 势函数奖励塑形（默认关闭，见 docs/REWARD_SHAPING.md）----
    ap.add_argument("--shaping-coef", type=float, default=0.0,
                    help="势函数奖励塑形系数 λ；0=关闭（默认，records/GAE 与旧路径逐位等价）")
    ap.add_argument("--shaping-gamma", type=float, default=None,
                    help="塑形折扣 γ_s（默认空=跟随训练 --gamma；只有与训练 γ 严格相等才满足"
                         "策略不变性；显式不一致会启动期警告并记录累计偏差）")
    ap.add_argument("--shaping-w-str", type=float, default=1.0,
                    help="Φ 的 Σ(atk+hp) 权重（默认 1.0）")
    ap.add_argument("--shaping-w-tier", type=float, default=0.5,
                    help="Φ 的 TIER_BONUS 权重（默认 0.5）")
    ap.add_argument("--shaping-tier-bonus", default="0,0,20,60,150,400,900",
                    help="按 tier 直接索引的奖励表（逗号分隔；索引 0=占位，越界按 0）")
    # ---- 等级进度奖励（tier-target，默认关闭，见 docs/TIER_TARGET.md）----
    ap.add_argument("--tier-target-coef", type=float, default=0.0,
                    help="等级进度奖励系数；0=关闭（默认，records/GAE 与旧路径逐位等价）")
    ap.add_argument("--tier-penalty", type=float, default=0.02,
                    help="某回合 tier 未达目标时该回合第一条 decision 的惩罚（乘 coef；默认 0.02）")
    ap.add_argument("--tier-bonus", type=float, default=0.15,
                    help="首次达标某回合目标时的一次性奖励（乘 coef；默认 0.15）")
    ap.add_argument("--tier-target-table", default="7:4,9:5,12:6",
                    help="目标曲线 turn:tier，逗号分隔（默认 7:4,9:5,12:6）")
    ap.add_argument("--library-p", type=float, default=0.0,
                    help="每回合每个 bot 座位的注入概率（建议 0.3 起）")
    ap.add_argument("--lockstep", type=int, default=0,
                    help="1=lock-step 批量 actor（每 worker 内多局同步推进）")
    ap.add_argument("--fast-act", type=int, default=1,
                    help="1=worker 侧采样（省 245 维 prior 回传）；0=旧路径（A/B 用）")
    ap.add_argument("--amp", default="off", choices=["off", "bf16"],
                    help="PPO 前向/反向精度；bf16 实测 2.03×（loss 侧仍 fp32）")
    ap.add_argument("--compile-train", type=int, default=0, choices=[0, 1, 2],
                    help="训练侧 torch.compile（只 learner 的 fwd+bwd + anchor 参考前向）："
                         "0=关（默认）1=默认模式 2=max-autotune。失败自动回退 eager；"
                         "叶前向/自对弈/评测路径不受影响（docs/TRAINING_COMPILE.md）")
    ap.add_argument("--anchor-amp", type=int, default=0, choices=[0, 1],
                    help="1=anchor 参考前向也用 --amp 的精度（bf16，实测约 1.8×）；"
                         "只影响 KL 正则项参考分布，默认 0=旧行为 fp32")
    ap.add_argument("--pi-coef", type=float, default=0.1)
    # ---- 动作序列辅助任务（默认关闭，见 docs/ACTION_SEQUENCE_AUX.md）----
    ap.add_argument("--seq-coef", type=float, default=0.0,
                    help="动作序列辅助头（该 seat 在本 turn 内动作 multi-hot 的 BCE）权重；"
                         "0=关闭（默认，records→batch→loss 与旧路径逐字节等价）")
    ap.add_argument("--seq-coef-ramp", default="",
                    help='按 decisions 比例的线性 ramp，如 "0.02@0,0.05@0.5"；'
                         "给了 ramp 时本 iteration 的系数由 ramp 决定")
    ap.add_argument("--seq-ramp-total-decisions", type=float, default=0.0,
                    help="ramp 的 100%% 进度对应的累计 decisions（0=用 --stop-at-decisions，"
                         "再缺省 30M）")
    # ---- 真实人类 BC 辅助正则（默认关闭，见 docs/BC_AUX.md）----
    ap.add_argument("--bc-coef", type=float, default=0.0,
                    help="真实人类对局（Firestone）BC 辅助 CE 权重（形态 A）；"
                         "0=关闭（默认，不加载 BC、不采样、loss 与旧路径逐位等价）")
    ap.add_argument("--bc-coef-ramp", default="",
                    help='BC 系数 ramp（与 --seq-coef-ramp 同语法），如 "0.005@0,0.02@0.3"；'
                         "按累计 decisions 求值后写回 bc_coef")
    ap.add_argument("--bc-mmr-min", type=int, default=6000,
                    help="BC 样本 MMR 下限（低于该值丢弃；默认 6000）")
    ap.add_argument("--bc-mmr-boost", type=float, default=1.0,
                    help="MMR 线性增强：1=不加权（默认）；1.5=在 6000..8000 上从 1.0 线性升到 1.5")
    ap.add_argument("--bc-class-weight", default="",
                    help='稀有动作类别权重覆盖，如 "upgrade=4,hero_power=2"；'
                         "在 class-balanced 权重之上再乘。空=现状（默认）")
    ap.add_argument("--bc-samples", default="data/firestone_bc/bc_samples.jsonl.gz",
                    help="BC 样本 JSONL(.gz) 路径（默认仓库 data/firestone_bc/bc_samples.jsonl.gz）")
    ap.add_argument("--bc-batch", type=int, default=128,
                    help="每个 PPO 微批抽取/编码的 BC 样本数（默认 128；固定形状编译）")
    ap.add_argument("--bc-every", type=int, default=1,
                    help="每 N 个 PPO 微批做一次 BC（默认 1=每个微批）；N>1 时该步 "
                         "BC 权重乘 N 保持等效平均权重，跳过步不跑 forward_bc")
    ap.add_argument("--bc-compile", type=int, default=1, choices=[0, 1],
                    help="--compile-train>0 时是否也把 BC 批次单独 torch.compile（默认 1）；"
                         "0=BC 保持 eager（A/B 基线，其余不变）")
    ap.add_argument("--bc-type-weight", type=float, default=1.0,
                    help="分层 BC 的类型级 CE 权重（9 类 log-sum-exp 聚合；默认 1.0）")
    ap.add_argument("--bc-card-weight", type=float, default=0.5,
                    help="分层 BC 的卡牌身份 CE 权重（3983 类 card_head，仅 buy/play；"
                         "默认 0.5；0=不建/不用 card_head）")
    ap.add_argument("--dpo-coef", type=float, default=0.0,
                    help="upgrade 子集 one-sided DPO 系数（0=关闭，默认）；每 "
                         "--dpo-every 个 iteration 把 coef*L_dpo 加进同一次 backward，"
                         "见 docs/DPO_UPGRADE.md")
    ap.add_argument("--dpo-beta", type=float, default=0.1,
                    help="DPO 温度 β（-logsigmoid(β·Δlogp)；默认 0.1）")
    ap.add_argument("--dpo-batch", type=int, default=128,
                    help="每个 DPO 步从 upgrade 池无放回抽样的样本数（默认 128）")
    ap.add_argument("--dpo-every", type=int, default=4,
                    help="DPO 周期，按 **iteration** 计（默认 4=每 4 个 iteration 一次）；"
                         "系数不做周期折算，平均梯度占比 ≈ coef/every")
    ap.add_argument("--dpo-samples", default="data/firestone_bc/bc_samples.jsonl.gz",
                    help="upgrade 样本来源 JSONL(.gz)（只读 action_type==upgrade 的行）；"
                         "默认 data/firestone_bc/bc_samples.jsonl.gz")
    # ---- 场面题（自对弈关键局面 + 人类参考解）与强度辅助头（默认关闭）----
    # 见 docs/RESEARCH_PLAN_V2.md §4.1 与 docs/BOARD_PROBLEMS.md。
    ap.add_argument("--problem-pool", default="data/board_problems/problems.jsonl",
                    help="场面题池（scripts/build_board_problems.py 产出）；"
                         "两个系数都为 0 时不读该文件")
    ap.add_argument("--problem-bc-coef", type=float, default=0.0,
                    help="场面题 soft-label CE 系数（0=关闭，默认）；只在题目状态上算，"
                         "与 BC/DPO 正交。>0 需要 --problem-pool 存在且模型支持 "
                         "forward_problem")
    ap.add_argument("--problem-bc-every", type=int, default=1,
                    help="场面题 CE 周期（按 iteration；默认 1=每次）")
    ap.add_argument("--problem-batch", type=int, default=128,
                    help="每批题目行数（题目 CE 与强度辅助头共用同一批 + 同一次前向）")
    ap.add_argument("--strength-aux-coef", type=float, default=0.0,
                    help="强度辅助头系数（0=关闭，默认）：t+3 战团强度增量的 log1p "
                         "回归 + tier+1 二分类，只在有标注（t+3 时存活）的题目上算")
    ap.add_argument("--strength-aux-every", type=int, default=1,
                    help="强度辅助头周期（按 iteration；默认 1=每次）")
    ap.add_argument("--strength-tier-pos-weight", type=float, default=1.0,
                    help="强度辅助头 tier+1 BCE 的正样本权重（默认 1.0）")
    ap.add_argument("--strength-head-init", default="fit", choices=["fit", "random"],
                    help="强度辅助头初始化：fit=在题目池上离线拟合线性头（CV 选 lambda "
                         "的 ridge + logistic，并冻结；推荐，40-60 iter 的小 lr 下随机头"
                         "无法校准）、random=保持 nn.Linear 随机初始化（纯消融）")
    ap.add_argument("--strength-head-ridge", type=float, default=1.0,
                    help="离线拟合的 ridge 强度（乘以样本数；默认 1.0）")
    ap.add_argument("--entropy-coef", type=float, default=0.005)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--workers", type=int, default=1,
                    help=">1 时使用并行采集 + 共享批量叶 server（非 pool 路径）")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--processes", type=int, default=1,
                    help=">1 时用进程级 actor pool（每进程绑定一张 GPU）")
    ap.add_argument("--gpus", default="",
                    help="actor pool 使用的物理 GPU 序号（任意列表，如 1,3,0,4,5；"
                         "不要设 CUDA_VISIBLE_DEVICES）")
    ap.add_argument("--gpu-free-check", type=int, default=1,
                    help="1=启动 actor pool 前用 nvidia-smi 剔除已被占用的 GPU"
                         "（邻居抢占；0=不检查）")
    ap.add_argument("--gpu-free-mib", type=int, default=1024,
                    help="--gpu-free-check 阈值：已用显存 > 该值（MiB）视为被占用")
    ap.add_argument("--threads", type=int, default=16,
                    help="每个 actor 进程内的采集线程数（每轮 games 应 >= processes*threads）")
    ap.add_argument("--pipeline", type=int, default=0,
                    help="1=double-buffer：collect(k+1) 与 update(k) 并行（需 --processes>1）")
    ap.add_argument("--pipeline-guard", default="warn", choices=["warn", "abort"],
                    help="流水线的 ratio 守卫触发时：warn 只记录，abort 立即保存并退出")
    ap.add_argument("--keep-versions", type=int, default=3,
                    help="保留几个历史权重文件（流水线用；每个 61 MB）")
    ap.add_argument("--snapshot-every", type=int, default=1,
                    help="每 N 个 iteration 落一次快照（进程 actor 下建议 5）")
    ap.add_argument("--keep-snapshots", type=int, default=3,
                    help="只保留最近 K 个 snapshot 目录（0=不清理）")
    ap.add_argument("--anchor-beta", type=float, default=0.0,
                    help="KL anchor 系数 β（论文 Table 7 = 0.1；0=关闭）")
    ap.add_argument("--anchor-iterations", type=int, default=100,
                    help="β 生效的前 N 个 iteration（论文 300 个中的前 100）")
    ap.add_argument("--anchor-beta-tail", type=float, default=0.0,
                    help="前 N 个 iteration 之后保留的 anchor β（stage-3 建议 0.02；0=旧行为）")
    ap.add_argument("--eval-every-decisions", type=int, default=0,
                    help="每累计 N decisions 做一次 C0 评测（0=关闭）")
    ap.add_argument("--eval-games", type=int, default=512)
    ap.add_argument("--eval-seats", type=int, default=8)
    ap.add_argument("--eval-seed-base", type=int, default=420000)
    ap.add_argument("--eval-async", type=int, default=0,
                    help="1=异步评测：ckpt 交给独立子进程跑 c0_gate，主循环不等待"
                         "（并发上限 1；默认 0=同步阻塞，旧行为）")
    ap.add_argument("--eval-device", default="",
                    help="评测用的 GPU（同步默认跟随 --device；异步默认 cuda:4）")
    ap.add_argument("--eval-drain", type=int, default=0,
                    help="1=训练退出时等待在跑的异步评测完成（默认 0=直接终止，不拖 wall）")
    ap.add_argument("--eval-stop-mean-rank", type=float, default=0.0,
                    help="评测 mean_rank <= 该值时在下一个 iteration 边界停止训练"
                         "（0=关闭；异步/同步共用，结果到达时判定）")
    ap.add_argument("--eval-panel", default="both", choices=["bot", "human", "both"],
                    help="周期评测面板：bot=256/512 局 bot 面板（已饱和）；human=人类战团"
                         "对手面板（新主指标）；both=两个面板各起一个子进程串行排队"
                         "（默认 both；并发上限仍为 1）")
    ap.add_argument("--eval-human-quantile", default="auto",
                    choices=["auto", "p50", "p75", "p90"],
                    help="human 面板的对手强度分位：auto=t<=8 p50 / 9-12 p75 / >=13 p90"
                         "（默认，见 docs/EVAL_PANELS.md）")
    ap.add_argument("--eval-human-boards", default="",
                    help="human 面板使用的人类战团 JSONL（空=默认 "
                         "data/real_library/library_real_degraded.jsonl）")
    ap.add_argument("--eval-human-baseline-bot", type=int, default=0,
                    help="1=human 面板同 seed 再跑 bot 基线（配对 CI；默认 0=只评 learner，"
                         "省一半 wall；TRIGGER/早停只看 bot 面板）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--trainer-state", default="")
    ap.add_argument("--out", default="runs/az_entity_sync")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)
    if float(args.library_p) > 0.0:
        print("[error] --library-p（v1 单座位注入）未通过终审，已禁用；"
              "请用 --trajectory-pool/--trajectory-p", file=sys.stderr)
        return 2
    # 回合末场面快照镜像（默认关闭；--mirror-p 0 且无 ramp 时完全零影响）
    _mirror_ramp = str(args.mirror_p_ramp).strip()
    if _mirror_ramp:
        try:
            ramp_p(0, _mirror_ramp)      # 提前校验格式，避免训练中途才报错
        except ValueError as exc:
            print(f"[error] --mirror-p-ramp 格式错误: {exc}", file=sys.stderr)
            return 2
    if (float(args.mirror_p) > 0.0 or _mirror_ramp) and int(args.mirror_seats) <= 0:
        print("[error] --mirror-p>0/--mirror-p-ramp 需要 --mirror-seats>0"
              "（给随机/固定座位注入）", file=sys.stderr)
        return 2
    if (float(args.mirror_p) > 0.0 or _mirror_ramp) and not int(args.lockstep):
        print("[warn] 回合末快照镜像只在 --lockstep 1 路径生效", flush=True)
    if str(args.mirror_snaps) and not os.path.isdir(str(args.mirror_snaps)):
        print(f"[warn] --mirror-snaps 目录不存在: {args.mirror_snaps}", flush=True)
    # 人类战团（board-only）注入（默认关闭；--human-board-p 0 时完全零影响）
    if float(args.human_board_p) > 0.0:
        if int(args.human_board_seats) <= 0:
            print("[error] --human-board-p>0 需要 --human-board-seats>0", file=sys.stderr)
            return 2
        if not str(args.human_boards):
            args.human_boards = "data/real_library/library_real_degraded.jsonl"
        if not os.path.isfile(str(args.human_boards)):
            print(f"[error] --human-boards 文件不存在: {args.human_boards}", file=sys.stderr)
            return 2
        _fid = str(getattr(args, "human_board_fidelity", "board") or "board")
        if _fid != "board":
            _need_rows = 0
            try:
                _need_rows = sum(1 for _ in open(args.human_boards, encoding="utf-8")
                                 if '"board_detail"' in _)
            except BaseException:  # noqa: BLE001
                _need_rows = 0
            if _need_rows <= 0:
                print(f"[error] --human-board-fidelity={_fid} 需要准完整库"
                      "（含 board_detail 的行）；当前文件没有："
                      f"{args.human_boards}\n"
                      "  先跑 PYTHONPATH=rust/python:. python "
                      "scripts/build_fidelity_library.py --stats", file=sys.stderr)
                return 2
            print(f"[info] 人类战团保真度 = {_fid}（准完整行 {_need_rows}；"
                  "注入走 apply_turn_snapshots + ended_turn 复位）", flush=True)
        if not int(args.lockstep):
            print("[warn] 人类战团注入只在 --lockstep 1 路径生效", flush=True)
        elif (float(args.mirror_p) > 0.0 or _mirror_ramp):
            print("[info] 人类战团 + 回合末快照镜像同时开启："
                  "同座位同回合镜像快照优先（记 human_board_skipped_by_mirror）", flush=True)
    elif str(args.human_boards):
        print("[warn] --human-boards 已设置但 --human-board-p=0：本次不注入", flush=True)

    # ---- 势函数奖励塑形（默认关闭；coef=0 时零影响）----
    if float(args.shaping_coef) < 0.0:
        print("[error] --shaping-coef 必须 >= 0", file=sys.stderr)
        return 2
    try:
        parse_tier_bonus(str(args.shaping_tier_bonus))   # 启动期 fail-fast
    except ValueError as exc:
        print(f"[error] --shaping-tier-bonus 非法: {exc}", file=sys.stderr)
        return 2
    # 折扣范围与一致性：γ_s 缺省 = 跟随训练 γ；显式不一致必须警告（不静默）
    if not (0.0 <= float(args.gamma) <= 1.0):
        print("[error] --gamma 必须在 [0, 1] 内", file=sys.stderr)
        return 2
    if args.shaping_gamma is not None and not (0.0 <= float(args.shaping_gamma) <= 1.0):
        print("[error] --shaping-gamma 必须在 [0, 1] 内", file=sys.stderr)
        return 2
    shape_gamma = (float(args.gamma) if args.shaping_gamma is None
                   else float(args.shaping_gamma))
    shape_aligned = (shape_gamma == float(args.gamma))
    if float(args.shaping_coef) > 0.0:
        if str(args.opponent) == "self":
            print("[error] 奖励塑形只支持 --opponent bot|weak（单 learner seat）",
                  file=sys.stderr)
            return 2
        if int(args.rust_collector):
            print("[error] Rust 采集器暂不支持奖励塑形；请设 --shaping-coef 0 "
                  "或 --rust-collector 0", file=sys.stderr)
            return 2
        print(f"[shaping] 势函数奖励塑形开启: coef={float(args.shaping_coef):g} "
              f"γ_s={shape_gamma:g}（训练 γ={float(args.gamma):g}，"
              f"{'对齐' if shape_aligned else '不一致'}） "
              f"Φ={float(args.shaping_w_str):g}*Σ(atk+hp)+"
              f"{float(args.shaping_w_tier):g}*tier_bonus "
              f"tier_bonus={args.shaping_tier_bonus}", flush=True)
        if not shape_aligned:
            print("[shaping][warn] " + shaping_gamma_warning(
                float(args.shaping_coef), shape_gamma, float(args.gamma)),
                file=sys.stderr, flush=True)
        if not int(args.lockstep):
            print("[info] 非 lockstep 路径：塑形在逐局采集（collect_ppo_records_parallel）"
                  "内生效", flush=True)

    # ---- 换位去抖守卫（默认关闭；--move-guard 0 时零影响）----
    if int(args.move_cap) < 0:
        print("[error] --move-cap 必须 >= 0", file=sys.stderr)
        return 2
    if int(args.move_repeat_limit) < 1:
        print("[error] --move-repeat-limit 必须 >= 1", file=sys.stderr)
        return 2
    if int(args.move_guard):
        if int(args.rust_collector):
            print("[error] Rust 采集器不支持换位守卫（它不经 PPOSelfPlayPolicy 采样）；"
                  "请设 --move-guard 0 或 --rust-collector 0", file=sys.stderr)
            return 2
        print(f"[move-guard] 换位去抖守卫开启: cap={int(args.move_cap)} "
              f"repeat_limit={int(args.move_repeat_limit)} "
              f"（逆换位 + 同动作超限 + 每回合 cap，见 docs/MOVE_GUARD.md）",
              flush=True)
        if not int(args.lockstep):
            print("[info] 非 lockstep 路径：守卫在逐局采集（collect_ppo_records_parallel）"
                  "内同样生效", flush=True)

    # ---- 等级进度奖励（tier-target，默认关闭；coef=0 时零影响）----
    if float(args.tier_target_coef) < 0.0:
        print("[error] --tier-target-coef 必须 >= 0", file=sys.stderr)
        return 2
    if float(args.tier_penalty) < 0.0 or float(args.tier_bonus) < 0.0:
        print("[error] --tier-penalty / --tier-bonus 必须 >= 0", file=sys.stderr)
        return 2
    try:
        parse_tier_target_table(str(args.tier_target_table))
    except ValueError as exc:
        print(f"[error] --tier-target-table 非法: {exc}", file=sys.stderr)
        return 2
    if float(args.tier_target_coef) > 0.0:
        if str(args.opponent) == "self":
            print("[error] 等级进度奖励只支持 --opponent bot|weak（单 learner seat）",
                  file=sys.stderr)
            return 2
        if int(args.rust_collector):
            print("[error] Rust 采集器暂不支持等级进度奖励；请设 --tier-target-coef 0 "
                  "或 --rust-collector 0", file=sys.stderr)
            return 2
        print(f"[tier-target] 等级进度奖励开启: coef={float(args.tier_target_coef):g} "
              f"penalty={float(args.tier_penalty):g} bonus={float(args.tier_bonus):g} "
              f"table={args.tier_target_table}", flush=True)
        if not int(args.lockstep):
            print("[info] 非 lockstep 路径：等级进度奖励在逐局采集"
                  "（collect_ppo_records_parallel / collect_ppo_batch）内生效", flush=True)

    # ---- 动作序列辅助任务：系数 ramp（默认关闭 = 零影响）----
    try:
        seq_schedule = SeqCoefSchedule.from_spec(
            base_coef=float(args.seq_coef), spec=str(args.seq_coef_ramp),
            total_decisions=(float(args.seq_ramp_total_decisions) if
                             float(args.seq_ramp_total_decisions) > 0 else
                             (float(args.stop_at_decisions) if
                              float(args.stop_at_decisions) > 0 else 3.0e7)))
    except ValueError as exc:
        print(f"[error] --seq-coef-ramp 非法: {exc}", file=sys.stderr)
        return 2
    seq_enabled = bool(seq_schedule.enabled)
    if seq_enabled:
        print(f"[seq] 动作序列辅助任务开启: {json.dumps(seq_schedule.describe(), ensure_ascii=False)}"
              f" coef(dec=0)={seq_schedule.coef(0):.4f}", flush=True)
    elif float(args.seq_coef) < 0.0:
        print("[error] --seq-coef 必须 >= 0", file=sys.stderr)
        return 2

    # ---- 注入（镜像快照 / 人类战团）：先校验引擎构建是否带注入 API ----
    # 典型事故：conda env 里 `hsbg_engine` 指向旧 clone（/tmp/...），训练命令又没设
    # PYTHONPATH → worker 每回合 AttributeError，注入全部静默失败。这里在父进程
    # 启动前 fail-fast，并给出修复命令。
    _inject_wanted = bool(int(args.lockstep)) and (
        (bool(args.mirror_snaps) and int(args.mirror_seats) > 0
         and (float(args.mirror_p) > 0.0 or str(args.mirror_p_ramp).strip()))
        or (bool(args.human_boards) and int(args.human_board_seats) > 0
            and float(args.human_board_p) > 0.0))
    if _inject_wanted:
        try:
            import hsbg_engine as _engine
            _need = []
            if bool(args.mirror_snaps) and int(args.mirror_seats) > 0 and \
                    (float(args.mirror_p) > 0.0 or str(args.mirror_p_ramp).strip()):
                _need.append("apply_turn_snapshots")
            if bool(args.human_boards) and int(args.human_board_seats) > 0 and \
                    float(args.human_board_p) > 0.0:
                _need.append("inject_board")
            _missing = [n for n in _need if not hasattr(_engine.Game, n)]
        except Exception as exc:  # noqa: BLE001
            print(f"[error] 无法 import hsbg_engine：{exc!r}", file=sys.stderr)
            return 2
        if _missing:
            print("[error] 当前 hsbg_engine 缺少注入 API "
                  f"{_missing}（import 自 {getattr(_engine, '__file__', '?')}）。"
                  "这是旧构建，注入会 100% 静默失败。请设置 "
                  "`PYTHONPATH=rust/python:.` 或 `pip install -e rust/python` 后重跑。",
                  file=sys.stderr)
            return 2

    # ---- 真实人类 BC 辅助正则：系数 ramp + 预加载池（默认关闭 = 零影响）----
    if float(args.bc_coef) < 0.0:
        print("[error] --bc-coef 必须 >= 0", file=sys.stderr)
        return 2
    if int(args.bc_batch) <= 0 or int(args.bc_every) <= 0:
        print("[error] --bc-batch 必须 > 0 且 --bc-every 必须 >= 1", file=sys.stderr)
        return 2
    if float(args.bc_type_weight) < 0.0 or float(args.bc_card_weight) < 0.0:
        print("[error] --bc-type-weight/--bc-card-weight 必须 >= 0", file=sys.stderr)
        return 2
    # ---- upgrade 子集 DPO（默认关闭 = 零影响）：系数/β/批量/周期校验 ----
    if not np.isfinite(float(args.dpo_coef)) or float(args.dpo_coef) < 0.0:
        print("[error] --dpo-coef 必须 >= 0", file=sys.stderr)
        return 2
    if not np.isfinite(float(args.dpo_beta)) or float(args.dpo_beta) <= 0.0:
        print("[error] --dpo-beta 必须是有限正数", file=sys.stderr)
        return 2
    if int(args.dpo_batch) <= 0 or int(args.dpo_every) <= 0:
        print("[error] --dpo-batch 必须 > 0 且 --dpo-every 必须 >= 1", file=sys.stderr)
        return 2
    # 场面题 / 强度辅助头（默认关闭）：系数非负、批量/周期合法
    for _nm in ("problem_bc_coef", "strength_aux_coef"):
        _v = float(getattr(args, _nm))
        if not np.isfinite(_v) or _v < 0.0:
            print(f"[error] --{_nm.replace('_', '-')} 必须 >= 0", file=sys.stderr)
            return 2
    for _nm in ("problem_batch", "problem_bc_every", "strength_aux_every"):
        if int(getattr(args, _nm)) <= 0:
            print(f"[error] --{_nm.replace('_', '-')} 必须 >= 1", file=sys.stderr)
            return 2
    _strength_enabled = bool(float(args.strength_aux_coef) > 0.0)
    _problem_enabled = bool(float(args.problem_bc_coef) > 0.0)
    _board_enabled = bool(_strength_enabled or _problem_enabled)
    try:
        bc_class_weights = parse_bc_class_weights(str(args.bc_class_weight))
    except ValueError as exc:
        print(f"[error] --bc-class-weight 非法: {exc}", file=sys.stderr)
        return 2
    try:
        bc_schedule = SeqCoefSchedule.from_spec(
            base_coef=float(args.bc_coef), spec=str(args.bc_coef_ramp),
            total_decisions=(float(args.stop_at_decisions) if
                             float(args.stop_at_decisions) > 0 else 3.0e7))
    except ValueError as exc:
        print(f"[error] --bc-coef-ramp 非法: {exc}", file=sys.stderr)
        return 2
    bc_enabled = bool(bc_schedule.enabled)
    if bc_enabled and float(args.bc_type_weight) <= 0.0 \
            and float(args.bc_card_weight) <= 0.0:
        print("[warn] BC 已启用但两层权重都为 0：自动关闭 bc_coef=0", flush=True)
        bc_enabled = False
        args.bc_coef = 0.0
        args.bc_coef_ramp = ""
    #: 是否构建/使用卡牌身份头（只在 BC 启用且 card 权重 > 0 时；bc_coef=0 不建）
    bc_card_head = bool(bc_enabled and float(args.bc_card_weight) > 0.0)
    bc_pool = None
    if bc_enabled:
        try:
            _t_bc = time.time()
            bc_pool = load_bc_samples(
                str(args.bc_samples), mmr_min=int(args.bc_mmr_min),
                mmr_boost=float(args.bc_mmr_boost),
                class_weight_overrides=(bc_class_weights or None))
            if len(bc_pool) == 0:
                raise ValueError("过滤后样本数为 0（动作白名单/MMR 下限）")
            _sum = bc_pool_summary(bc_pool)
            print(f"[bc] 真实人类 BC 池: samples={len(bc_pool)} "
                  f"mmr>={int(args.bc_mmr_min)} load={time.time() - _t_bc:.1f}s "
                  f"path={bc_pool.path}", flush=True)
            print(f"[bc] class_counts={json.dumps(_sum['class_counts'], ensure_ascii=False)}",
                  flush=True)
            print(f"[bc] class_fractions="
                  f"{json.dumps({k: round(v, 4) for k, v in _sum['class_fractions'].items()}, ensure_ascii=False)}",
                  flush=True)
            print(f"[bc] 分层目标: type_weight={float(args.bc_type_weight):g} "
                  f"card_weight={float(args.bc_card_weight):g} "
                  f"card_head={'on' if bc_card_head else 'off'} "
                  f"class_weights={json.dumps(bc_class_weights, ensure_ascii=False)} "
                  f"coef(dec=0)={bc_schedule.coef(0):.4g} "
                  f"ramp={json.dumps(bc_schedule.describe(), ensure_ascii=False)}",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 - BC 可选，失败自动关闭
            print(f"[warn] BC 数据加载失败，自动关闭 bc_coef=0（不中断训练）："
                  f"{type(exc).__name__}: {exc}", flush=True)
            bc_enabled = False
            bc_card_head = False
            args.bc_coef = 0.0
            args.bc_coef_ramp = ""
            bc_pool = None

    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2
    if not torch_available():
        print("[error] torch 不可用", file=sys.stderr)
        return 2
    import torch
    if args.minutes <= 0 or args.games <= 0 or args.iterations < 0:
        print("[error] minutes/games 必须 >0，iterations 必须 >=0", file=sys.stderr)
        return 2
    if args.workers <= 0 or args.batch_size <= 0:
        print("[error] workers/batch-size 必须 >0", file=sys.stderr)
        return 2
    if args.trainer_state and not os.path.isfile(args.trainer_state):
        print(f"[error] trainer-state 不存在: {args.trainer_state}", file=sys.stderr)
        return 2
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % (2 ** 32))
    os.makedirs(args.out, exist_ok=True)
    eng = engine_info()
    print(f"[engine] {json.dumps(eng, ensure_ascii=False)}", flush=True)

    norm_mean = norm_std = None
    if args.checkpoint:
        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        arch = str(meta.get("arch", args.arch))
        norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
        print(f"[net] checkpoint={args.checkpoint} arch={arch}", flush=True)
        # 有向 Move 头：旧 ckpt 没有 move_from/move_to 时，只追加两个投影并继承其余权重
        _move_split_loaded = bool(getattr(model, "move_head_split", False))
        if int(args.move_head_split) and not _move_split_loaded:
            _p0 = sum(p.numel() for p in model.parameters())
            try:
                attach_move_head_split(model)
            except ValueError as exc:
                print(f"[error] --move-head-split 1 不可用: {exc}", file=sys.stderr)
                return 2
            _p1 = sum(p.numel() for p in model.parameters())
            print(f"[net] move_head_split=on（旧 checkpoint 无有向 Move 投影）："
                  f"已追加 move_from/move_to，参数 +{_p1 - _p0:,}"
                  f"（{_p0:,} -> {_p1:,}），其余权重继承", flush=True)
        elif _move_split_loaded:
            print("[net] move_head_split=on（checkpoint meta 已声明）", flush=True)
        if seq_enabled and getattr(model, "seq_head", None) is None:
            print("[warn] checkpoint 没有动作序列辅助头（旧 checkpoint）：本次关闭 seq 辅助任务",
                  flush=True)
            seq_enabled = False
        if bc_card_head and getattr(model, "card_head", None) is None:
            # 旧 checkpoint（如 champion_c0_1975）没有 card_head：加载后追加，
            # 随机初始化，随后由 BC 卡牌身份 CE 训练。
            try:
                attach_bc_card_head(model)
                print(f"[bc] checkpoint 无 card_head：已追加 "
                      f"Linear({bc_card_head_dim(model)}, 3983)", flush=True)
            except Exception as exc:  # noqa: BLE001 - 退化到只做类型级 BC
                print(f"[warn] 追加 card_head 失败（本次只用类型级 BC）：{exc!r}",
                      flush=True)
                bc_card_head = False
                args.bc_card_weight = 0.0
    elif args.trainer_state and os.path.isfile(args.trainer_state):
        # trainer.pt 的 model state 是 strict 加载：老 state 没有 card_head 时不能
        # 在加载前追加（会 unexpected key），因此 trainer-state 路径要求 state 已含该头。
        model = build_net(arch=args.arch, seq_head=seq_enabled,
                          bc_card_head=False)
        if int(args.move_head_split):
            print("[warn] --trainer-state 路径按 state 的架构加载；--move-head-split 1 "
                  "只对 --checkpoint（model.pt）生效，本次忽略", flush=True)
        meta = {"arch": args.arch}
        arch = args.arch
        print(f"[net] empty model for trainer-state={args.trainer_state}", flush=True)
    else:
        model = build_net(arch=args.arch, seq_head=seq_enabled,
                          bc_card_head=bc_card_head,
                          move_head_split=bool(int(args.move_head_split)))
        meta = {"arch": args.arch}
        arch = args.arch
    if bc_enabled and bc_card_head and getattr(model, "card_head", None) is None:
        print("[warn] 模型没有 card_head（trainer-state/旧 ckpt）：本次只用类型级 BC "
              "(bc_card_weight=0)", flush=True)
        bc_card_head = False
        args.bc_card_weight = 0.0
    model.to(torch.device(args.device))
    print(f"[net] arch={arch} params={sum(p.numel() for p in model.parameters()):,}",
          flush=True)

    # ---- 场面题池 + 强度辅助头（默认关闭 = 不读文件、不建头、零影响）----------
    # 题目池里同时有「人类参考动作 top-k 软标签」与「t+3 战团强度/tier+1 标签」：
    # 题目 CE 与强度辅助头共用同一批题目 + 同一次 forward_problem（B/C/D 三臂可比）。
    problem_pool = None
    if _board_enabled:
        try:
            from hsbg.az.train.board_problems import load_problem_pool
            _t_prob = time.time()
            problem_pool = load_problem_pool(str(args.problem_pool))
            if len(problem_pool) == 0:
                raise ValueError(f"题目池为空/不存在: {args.problem_pool}")
            _ps = problem_pool.summary()
            print(f"[problems] pool={problem_pool.path} n={_ps['problems']} "
                  f"bc_valid={_ps['bc_valid']}({_ps['bc_valid_rate']:.1%}) "
                  f"aux_valid={_ps['aux_valid']}({_ps['aux_valid_rate']:.1%}) "
                  f"turns={_ps['by_turn']} "
                  f"load={time.time() - _t_prob:.1f}s", flush=True)
            print(f"[problems] by_tag={json.dumps(_ps['by_tag'], ensure_ascii=False)} "
                  f"tier_up_rate={_ps['tier_up_rate']:.3f} "
                  f"strength_p50 before={_ps['strength_before_p50']:.0f} "
                  f"after={_ps['strength_after_p50']:.0f} "
                  f"norm={json.dumps(_ps['norm'], ensure_ascii=False)}", flush=True)
            if _problem_enabled and int(_ps["bc_valid"]) == 0:
                print("[warn] 题目池没有任何合法参考解（bc_valid=0）："
                      "自动关闭 problem_bc_coef=0", flush=True)
                args.problem_bc_coef = 0.0
                _problem_enabled = False
            if _strength_enabled and int(_ps["aux_valid"]) == 0:
                print("[warn] 题目池没有任何 t+3 强度标注（aux_valid=0）："
                      "自动关闭 strength_aux_coef=0", flush=True)
                args.strength_aux_coef = 0.0
                _strength_enabled = False
        except Exception as exc:  # noqa: BLE001 - 可选辅助，失败不中断训练
            print(f"[warn] 场面题池加载失败，自动关闭 problem_bc_coef/"
                  f"strength_aux_coef（不中断训练）：{type(exc).__name__}: {exc}",
                  flush=True)
            args.problem_bc_coef = 0.0
            args.strength_aux_coef = 0.0
            _problem_enabled = _strength_enabled = False
            problem_pool = None
    if _strength_enabled and problem_pool is not None:
        _snorm = dict(problem_pool.norm or {"mean": 0.0, "std": 1.0})
        if getattr(model, "strength_head", None) is None:
            try:
                attach_strength_head(model, norm=_snorm)
                print(f"[strength] checkpoint 无 strength_head：已追加 "
                      f"Linear({bc_card_head_dim(model)}, 2)（t+3 log1p 强度 + tier+1），"
                      f"norm={json.dumps(_snorm, ensure_ascii=False)}", flush=True)
            except Exception as exc:  # noqa: BLE001 - 非 entity/测试替身
                print(f"[warn] 追加 strength_head 失败（本次关闭 strength_aux_coef=0）："
                      f"{exc!r}", flush=True)
                args.strength_aux_coef = 0.0
                _strength_enabled = False
        else:
            model.strength_norm = _snorm
            print(f"[strength] checkpoint 已带 strength_head（沿用权重）；"
                  f"norm={json.dumps(_snorm, ensure_ascii=False)}", flush=True)
        if str(args.strength_head_init) == "fit":
            from hsbg.az.train.board_problems import fit_strength_head
            try:
                _rep = fit_strength_head(
                    model, problem_pool, ridge=float(args.strength_head_ridge),
                    device=str(args.device))
                print(f"[strength] 离线拟合线性头（题目池 aux_valid="
                      f"{_rep['n']}）：mse={_rep['mse']:.4f} bce={_rep['bce']:.4f} "
                      f"tier_acc={_rep['tier_acc']:.3f} "
                      f"cv_mse={_rep.get('cv_mse', float('nan')):.4f} "
                      f"pearson(增量)={_rep['pearson_delta']:.3f} "
                      f"ridge={_rep['ridge']:g} frozen={_rep['frozen']}", flush=True)
            except Exception as exc:  # noqa: BLE001 - 拟合失败保留随机头
                print(f"[warn] 强度头离线拟合失败（保留随机初始化）："
                      f"{type(exc).__name__}: {exc}", flush=True)
    if (_problem_enabled or _strength_enabled):
        print(f"[problems] problem_bc_coef={float(args.problem_bc_coef):g} "
              f"every={int(args.problem_bc_every)} "
              f"strength_aux_coef={float(args.strength_aux_coef):g} "
              f"every={int(args.strength_aux_every)} "
              f"batch={int(args.problem_batch)} "
              f"tier_pos_weight={float(args.strength_tier_pos_weight):g}", flush=True)

    # ---- upgrade 子集 DPO：预加载池 + 启动诊断（默认关闭 = 零影响）------------
    # 池 ~3050 条 / ~7s；只在 --dpo-coef>0 时加载。失败自动关闭（不中断训练）。
    dpo_pool: Optional[UpgradeSamples] = None
    if float(args.dpo_coef) > 0.0:
        try:
            _t_dpo = time.time()
            dpo_pool = load_upgrade_samples(str(args.dpo_samples))
            if len(dpo_pool) == 0:
                raise ValueError("过滤后样本数为 0（动作白名单/MMR 下限）")
            print(f"[dpo] upgrade 池: samples={len(dpo_pool)} "
                  f"mmr>={int(dpo_pool.mmr_min)} "
                  f"load={time.time() - _t_dpo:.1f}s path={dpo_pool.path}",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 - DPO 可选，失败自动关闭
            print(f"[warn] upgrade DPO 样本加载失败，自动关闭 dpo_coef=0"
                  f"（不中断训练）：{type(exc).__name__}: {exc}", flush=True)
            args.dpo_coef = 0.0
            dpo_pool = None
    if dpo_pool is not None and len(dpo_pool) > 0:
        # 启动诊断：当前策略在池上的 DPO 初值 / 接受率（no_grad，不改权重）
        _p = _dpo_startup_probe(model, dpo_pool, beta=float(args.dpo_beta),
                                device=str(args.device))
        _term = float(args.dpo_coef) * float(_p["loss"])
        _avg = _term / float(max(1, int(args.dpo_every)))
        _ref, _ref_src = _ppo_total_ref(str(args.out))
        print(f"[dpo] beta={float(args.dpo_beta):g} coef={float(args.dpo_coef):g} "
              f"batch={int(args.dpo_batch)} every={int(args.dpo_every)} "
              f"（每 {int(args.dpo_every)} 个 iteration 加一次 coef*L_dpo）", flush=True)
        print(f"[dpo] 当前策略 on 池: dpo_loss={_p['loss']:.4f} "
              f"accept_rate={_p['accept_rate']:.3f}（n={int(_p['n'])}）"
              f" -> 单步项={_term:.5f}，平均/iteration={_avg:.5f}", flush=True)
        print(f"[dpo] 期望梯度占比（loss 标度参考）: 单步 DPO 项 / |PPO total| ≈ "
              f"{_term / max(abs(_ref), 1e-9) * 100:.2f}%（参考 total={_ref:.4f}，"
              f"来自{_ref_src}）", flush=True)
        _gref = _dpo_grad_ref()
        if _gref is not None:
            _gc = float(args.dpo_coef) * float(_gref["share_per_coef"])
            print(f"[dpo] 期望梯度占比（实测 ‖g_dpo‖/‖g_ppo‖，"
                  f"来自 {_gref['path']}）: 单步≈{_gc * 100:.2f}%，"
                  f"平均/iteration≈{_gc / max(1, int(args.dpo_every)) * 100:.2f}%",
                  flush=True)
        else:
            print("[dpo] 期望梯度占比：暂无实测梯度范数比（可跑 "
                  "scripts/dpo_grad_probe.py 生成 runs/dpo_grad_probe.json）",
                  flush=True)

    p_cfg = PPOConfig(
        epochs=int(args.epochs), minibatch=int(args.minibatch), lr=float(args.lr),
        clip=float(args.clip), gamma=float(args.gamma),
        target_kl=float(args.target_kl),
        entropy_coef=float(args.entropy_coef), pi_coef=float(args.pi_coef),
        max_grad_norm=float(args.max_grad_norm),
        grad_accum=int(args.grad_accum), amp=str(args.amp),
        device=str(args.device), seed=int(args.seed),
        log_every=int(args.log_every),
        compile_train=int(args.compile_train),
        anchor_amp=bool(int(args.anchor_amp)),
        # 动作序列辅助任务：初始系数由 ramp 在 dec=0 处给出（无 ramp 时=--seq-coef）
        seq_coef=(seq_schedule.coef(0) if seq_enabled else 0.0),
        seq_coef_ramp=(str(args.seq_coef_ramp) if seq_enabled else ""),
        # 真实人类 BC 辅助正则（分层目标）：初始系数由 ramp 在 dec=0 处给出；
        # 池在下方注入 trainer。
        bc_coef=(bc_schedule.coef(0) if bc_enabled else 0.0),
        bc_coef_ramp=(str(args.bc_coef_ramp) if bc_enabled else ""),
        bc_mmr_min=int(args.bc_mmr_min),
        bc_mmr_boost=float(args.bc_mmr_boost),
        bc_class_weights=dict(bc_class_weights),
        bc_samples_path=str(args.bc_samples),
        bc_batch=int(args.bc_batch),
        bc_every=int(args.bc_every),
        bc_compile=int(args.bc_compile),
        bc_type_weight=float(args.bc_type_weight),
        bc_card_weight=float(args.bc_card_weight),
        # upgrade 子集 one-sided DPO：系数固定（无 ramp）；池在下方注入 trainer
        dpo_coef=float(args.dpo_coef),
        dpo_beta=float(args.dpo_beta),
        dpo_batch=int(args.dpo_batch),
        dpo_every=int(args.dpo_every),
        dpo_samples=str(args.dpo_samples),
        # 场面题 soft-label CE + 强度辅助头（默认关闭；池在下方注入 trainer）
        problem_bc_coef=float(args.problem_bc_coef),
        problem_bc_every=int(args.problem_bc_every),
        problem_batch=int(args.problem_batch),
        problem_pool_path=str(args.problem_pool),
        strength_aux_coef=float(args.strength_aux_coef),
        strength_aux_every=int(args.strength_aux_every),
        strength_tier_pos_weight=float(args.strength_tier_pos_weight))
    trainer: Optional[PPOTrainer] = None
    if args.trainer_state and os.path.isfile(args.trainer_state):
        trainer = PPOTrainer.load(model, args.trainer_state, config=p_cfg,
                                  device=args.device, bc_pool=bc_pool,
                                  dpo_pool=dpo_pool)
        print(f"[trainer] loaded updates={trainer.updates} "
              f"lr={trainer.optimizer.param_groups[0]['lr']:.3g}", flush=True)
    else:
        trainer = PPOTrainer(model, p_cfg, lr_min_ratio=float(args.lr_min_ratio),
                             max_updates=int(args.max_updates), bc_pool=bc_pool,
                             dpo_pool=dpo_pool)

    # BC 池注入（CLI 已预加载/打印；trainer 若自己加载过则复用）
    if bc_enabled:
        if bc_pool is not None:
            trainer.set_bc_pool(bc_pool)
        elif getattr(trainer, "bc_pool", None) is not None:
            bc_pool = trainer.bc_pool
        if getattr(trainer, "bc_pool", None) is None:
            print("[warn] BC 池不可用，自动关闭 bc_coef=0", flush=True)
            bc_enabled = False
            trainer.config.bc_coef = 0.0
            trainer.config.bc_coef_ramp = ""

    # upgrade DPO 池注入（CLI 已预加载/打印；trainer 若自己加载过则复用）
    dpo_enabled = bool(float(args.dpo_coef) > 0.0)
    if dpo_enabled:
        if dpo_pool is not None:
            trainer.set_dpo_pool(dpo_pool)
        elif getattr(trainer, "dpo_pool", None) is not None:
            dpo_pool = trainer.dpo_pool
            print(f"[dpo] 复用 trainer 已加载的 upgrade 池: samples={len(dpo_pool)}",
                  flush=True)
        if getattr(trainer, "dpo_pool", None) is None:
            print("[warn] upgrade DPO 池不可用，自动关闭 dpo_coef=0", flush=True)
            dpo_enabled = False
            trainer.config.dpo_coef = 0.0

    # 场面题池注入（CLI 已预加载/打印；未启用时为 None，trainer 不会自己加载）
    if _board_enabled and problem_pool is not None and not args.trainer_state:
        trainer.set_problem_pool(problem_pool)

    # ---- 日志：history.jsonl 追加（兼容旧 history.json）----
    history: List[Dict[str, Any]] = []
    history_path = os.path.join(args.out, "history.jsonl")
    legacy_history = os.path.join(args.out, "history.json")
    if args.trainer_state:
        if os.path.isfile(history_path):
            _, history = read_run(history_path)
        elif os.path.isfile(legacy_history):
            _, history = read_run(legacy_history)
    write_header(history_path, {k: v for k, v in vars(args).items()})

    if trainer.extra.get("norm_mean") is not None:
        norm_mean = np.asarray(trainer.extra["norm_mean"], dtype=np.float32)
    if trainer.extra.get("norm_std") is not None:
        norm_std = np.asarray(trainer.extra["norm_std"], dtype=np.float32)
    trainer.extra["norm_mean"] = (None if norm_mean is None else norm_mean.tolist())
    trainer.extra["norm_std"] = (None if norm_std is None else norm_std.tolist())
    start_i = int(trainer.updates)
    print(f"[resume] start_iter={start_i} updates={trainer.updates}", flush=True)

    # ---- KL anchor（AutoTavern Table 7：β=0.1，仅前 100 个 iteration）----
    if float(args.anchor_beta) > 0.0:
        trainer.set_anchor()
        print(f"[anchor] beta={args.anchor_beta} for first "
              f"{int(args.anchor_iterations)} iters (stage-start policy frozen)",
              flush=True)
    if int(args.compile_train) > 0:
        tf = getattr(trainer, "train_forward", None)
        if tf is None:
            print("[compile] train compile 请求但未生效（回退 eager）", flush=True)
        else:
            print(f"[compile] train compile={int(args.compile_train)} "
                  f"active={tf.active} main={tf.main_compiled} aux={tf.aux_compiled} "
                  f"warmup={tf.warmup_seconds:.1f}s"
                  + (f" warnings={tf.warnings}" if tf.warnings else ""), flush=True)
        af = getattr(trainer, "anchor_forward", None)
        if af is not None:
            print(f"[compile] anchor compile active={af.active} "
                  f"warmup={af.warmup_seconds:.1f}s", flush=True)

    # ---- 周期 C0 评测（监控曲线；avg rank<=3.0 触发镜像库）----
    # 同步（--eval-async 0，旧行为）在主循环里阻塞；异步（1）把 ckpt 丢给独立子进程，
    # 由轻量线程回收结果。两条路径共用 _post_eval 做 TRIGGER / 早停判定。
    evals: list = []
    eval_dir = os.path.join(args.out, "eval")
    eval_async = bool(int(args.eval_async))
    eval_device = str(args.eval_device or ("cuda:4" if eval_async else args.device))
    # panel 列表：bot=旧 c0_gate 面板；human=人类战团面板；both=两个子进程串行排队。
    eval_panels = panels_from_spec(args.eval_panel)
    eval_human_boards = str(args.eval_human_boards or os.path.join(
        ROOT, "data", "real_library", "library_real_degraded.jsonl"))
    if "human" in eval_panels and not os.path.isfile(eval_human_boards):
        print(f"[error] human 评测面板需要人类战团数据: {eval_human_boards}",
              file=sys.stderr)
        return 2
    eval_stop = threading.Event()
    eval_state: Dict[str, Any] = {"stop_reason": ""}
    eval_history_lock = threading.Lock()
    #: 最近一次各面板结果（写 history.jsonl 的 eval 段；bot -> mean_rank，
    #: human -> human_mean_rank，见 docs/EVAL_PANELS.md）
    latest_eval: Dict[str, Dict[str, Any]] = {}

    def _save_eval_ckpt(decisions_done: int) -> Tuple[str, str]:
        """落一份评测专用 ckpt（与训练权重解耦，子进程只读它）。"""
        os.makedirs(eval_dir, exist_ok=True)
        tag = f"{int(decisions_done):09d}"
        ckpt = os.path.join(eval_dir, f"ckpt_{tag}.pt")
        save_checkpoint(model, ckpt, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        return tag, ckpt

    def _post_eval(rec: Dict[str, Any]) -> None:
        """评测结果后处理（同步/异步共用，异步时在 monitor 线程执行）。"""
        panel = str(rec.get("panel") or "bot")
        has = (rec.get("human_mean_rank") is not None if panel == "human"
               else rec.get("mean_rank") is not None)
        with eval_history_lock:
            if has:
                latest_eval[panel] = dict(rec)
        # TRIGGER / 早停只按 bot 面板（旧语义），human 面板只作主指标记录。
        mr = rec.get("mean_rank") if panel == "bot" else None
        if mr is None:
            return
        mr = float(mr)
        if mr <= 3.0:
            trig = os.path.join(args.out, "TRIGGER_library.json")
            write_json_atomic(trig, {"decisions": int(rec["decisions"]),
                                     "mean_rank": mr,
                                     "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
            print(f"[TRIGGER] avg rank {mr:.3f} <= 3.0 -> "
                  f"构建高质量对局镜像库 ({trig})", flush=True)
        th = float(args.eval_stop_mean_rank)
        if th > 0.0 and mr <= th:
            eval_state["stop_reason"] = (f"mean_rank={mr:.4f} <= {th:.4f} "
                                         f"@dec={int(rec['decisions'])}")
            eval_stop.set()
            print(f"[eval] stop requested: {eval_state['stop_reason']} "
                  f"-> 下一个 iteration 边界停止", flush=True)

    def _eval_snapshot() -> Dict[str, Any]:
        """history.jsonl 的 ``eval`` 段：bot 面板 ``mean_rank`` + human 面板
        ``human_mean_rank``（两个键并存，方便画图脚本直接读）。"""
        with eval_history_lock:
            bot = dict(latest_eval.get("bot") or {})
            human = dict(latest_eval.get("human") or {})
            if not bot and not human:
                return {}
            return {
                "mean_rank": bot.get("mean_rank"),
                "human_mean_rank": human.get("human_mean_rank"),
                "bot_mean_rank": bot.get("bot_mean_rank"),
                "top4": bot.get("top4"),
                "win": bot.get("win"),
                "human_top4": human.get("human_top4"),
                "human_win": human.get("human_win"),
                "human_quantile": human.get("quantile"),
                "bot_decisions": bot.get("decisions"),
                "human_decisions": human.get("decisions"),
            }

    def _append_eval_history(rec: Dict[str, Any]) -> None:
        with eval_history_lock:
            evals.append(rec)
            write_json_atomic(os.path.join(eval_dir, "history.json"), {"evals": evals})

    def _run_eval(decisions_done: int) -> None:
        """同步评测：主循环阻塞到各 panel 的子进程依次结束。"""
        tag, ckpt = _save_eval_ckpt(decisions_done)
        for panel in eval_panels:
            prefix = "c0" if panel == "bot" else "human"
            out_json = os.path.join(eval_dir, f"{prefix}_{tag}.json")
            log_path = os.path.join(eval_dir, f"{prefix}_{tag}.log")
            if panel == "bot":
                cmd = build_c0_cmd(
                    sys.executable, ROOT, ckpt, arch=str(arch), device=eval_device,
                    games=int(args.eval_games), seats=int(args.eval_seats),
                    seed_base=int(args.eval_seed_base), out_json=out_json)
            else:
                cmd = build_human_cmd(
                    sys.executable, ROOT, ckpt, arch=str(arch), device=eval_device,
                    games=int(args.eval_games), seats=int(args.eval_seats),
                    seed_base=int(args.eval_seed_base), out_json=out_json,
                    quantile=str(args.eval_human_quantile),
                    human_boards=eval_human_boards,
                    baseline_bot=bool(int(args.eval_human_baseline_bot)))
            t_eval = time.time()
            print(f"[eval] dec={int(decisions_done)} panel={panel} "
                  f"start games={args.eval_games}", flush=True)
            with open(log_path, "w", encoding="utf-8") as lf:
                rc = subprocess.call(cmd, cwd=ROOT, stdout=lf, stderr=lf)
            rec = parse_panel_result(decisions_done, rc, time.time() - t_eval,
                                     out_json, panel=panel)
            _append_eval_history(rec)
            if panel == "human" and rec.get("human_mean_rank") is not None:
                print(f"[eval] dec={int(decisions_done)} panel=human "
                      f"human_mean_rank={rec['human_mean_rank']:.3f} "
                      f"top4={rec['human_top4']:.3f} win={rec['human_win']:.3f} "
                      f"({rec['seconds']}s)", flush=True)
            elif panel == "bot" and rec.get("mean_rank") is not None:
                print(f"[eval] dec={int(decisions_done)} panel=bot "
                      f"mean_rank={rec['mean_rank']:.3f} "
                      f"bot={rec['bot_mean_rank']:.3f} top4={rec['top4']:.3f} "
                      f"win={rec['win']:.3f} ({rec['seconds']}s)", flush=True)
            else:
                print(f"[eval] dec={int(decisions_done)} panel={panel} FAILED rc={rc} "
                      f"error={rec.get('error')} log={log_path}", flush=True)
            _post_eval(rec)

    # 异步评测：独立子进程 + 一个轻量回收线程（并发上限 1，提交本身只花 ~0.3s 存 ckpt）
    eval_runner: Optional[AsyncEvalRunner] = None
    if eval_async:
        eval_runner = AsyncEvalRunner(
            out_dir=args.out, root=ROOT, arch=arch, device=eval_device,
            games=int(args.eval_games), seats=int(args.eval_seats),
            seed_base=int(args.eval_seed_base),
            panels=eval_panels,
            human_quantile=str(args.eval_human_quantile),
            human_boards=eval_human_boards,
            baseline_bot=bool(int(args.eval_human_baseline_bot)),
            on_result=_post_eval)
        print(f"[eval-async] on：device={eval_device} games={args.eval_games} "
              f"seats={args.eval_seats} panels={eval_panels} "
              f"human_quantile={args.eval_human_quantile}；主循环不等待"
              f"（并发上限 1，panel 串行排队，drain={int(args.eval_drain)}）",
              flush=True)
        if int(args.eval_every_decisions) <= 0:
            print("[warn] --eval-async 1 但 --eval-every-decisions=0：不会触发评测",
                  flush=True)
        if str(eval_device).startswith("cuda") and int(args.gpu_free_check):
            try:
                _eidx = int(str(eval_device).split(":")[1]) if ":" in str(eval_device) else 0
            except ValueError:
                _eidx = None
            _used = _gpu_used_mib()
            if _eidx is not None and _used.get(_eidx, 0) > int(args.gpu_free_mib):
                print(f"[warn] 评测卡 {eval_device} 已被占用 "
                      f"{_used[_eidx]}MiB（>{int(args.gpu_free_mib)}MiB）：评测子进程可能 "
                      f"OOM/变慢，建议换 --eval-device（如 cuda:6/7）", flush=True)

    def _submit_eval(decisions_done: int) -> None:
        """异步提交：只保存 ckpt + spawn，不等待（跳过时 runner 自己记 eval_skipped）。

        已有一个评测在跑时**不落 61MB ckpt**：直接让 runner 记一条 skipped。
        """
        if eval_runner.running():
            eval_runner.submit(decisions_done, "")
            return
        _tag, ckpt = _save_eval_ckpt(decisions_done)
        eval_runner.submit(decisions_done, ckpt)

    search_fn = search_cfg = None
    if int(args.sims) > 0:
        try:
            from hsbg.az import SearchConfig, search as az_search
        except Exception as exc:  # noqa: BLE001
            print(f"[error] search unavailable: {exc!r}", file=sys.stderr)
            return 2
        search_cfg = SearchConfig(simulations=int(args.sims),
                                  determinizations=int(args.determinizations),
                                  seed=int(args.seed))
        search_fn = az_search

    # ---- actor pool / 单进程采集 ----
    pool: Optional[ProcessActorPool] = None
    pool_ckpt = os.path.join(args.out, "_pool_weights.pt")
    if int(args.processes) > 1:
        if not str(args.gpus).strip():
            print("[error] --processes>1 需要 --gpus（物理 GPU 序号）", file=sys.stderr)
            return 2
        if os.environ.get("CUDA_VISIBLE_DEVICES"):
            print("[error] 请 unset CUDA_VISIBLE_DEVICES：--gpus 用物理序号", file=sys.stderr)
            return 2
        gpus = [int(x) for x in str(args.gpus).split(",") if x.strip()]
        # 邻居抢占检测：显存已用 > 阈值（默认 1 GiB）的卡从 actor 列表剔除并 warn。
        # 失败（nvidia-smi 不可用）时不做剔除，按用户给的列表跑。
        if int(args.gpu_free_check):
            used = _gpu_used_mib()
            if used:
                threshold = int(args.gpu_free_mib)
                busy = [g for g in gpus if used.get(g, 0) > threshold]
                if busy:
                    detail = ", ".join(f"cuda:{g}={used.get(g)}MiB" for g in busy)
                    warn = (f"[warn] GPU 已被占用（>{threshold}MiB，疑似邻居进程）：{detail}"
                            f" -> 从 actor 列表剔除")
                    print(warn, flush=True)
                    gpus = [g for g in gpus if g not in busy]
                if not gpus:
                    print("[error] --gpu-free-check 后没有可用 GPU（可用 --gpu-free-check 0 "
                          "跳过检查）", file=sys.stderr)
                    return 2
        per_gpu = {g: sum(1 for k in range(int(args.processes)) if gpus[k % len(gpus)] == g)
                   for g in gpus}
        print(f"[pool] processes={int(args.processes)} gpus={gpus} "
              f"workers/gpu={per_gpu}", flush=True)
        if len(gpus) != len(set(gpus)):
            print(f"[warn] --gpus 有重复项: {gpus}", flush=True)
        save_checkpoint(model, pool_ckpt, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        pool = ProcessActorPool(
            int(args.processes), gpus, pool_ckpt, arch=arch,
            sims=int(args.sims), determinizations=int(args.determinizations),
            seed=int(args.seed), threads=int(args.threads),
            batch_size=int(args.batch_size),
            max_wait_ms=float(args.leaf_wait_ms),
            tmpdir=os.path.join(args.out, "_proc_tmp"))
        print(f"[pool] {json.dumps(pool.describe(), ensure_ascii=False)}", flush=True)
        if eval_async and str(eval_device).startswith("cuda"):
            try:
                _eidx = int(str(eval_device).split(":")[1]) if ":" in str(eval_device) else 0
            except ValueError:
                _eidx = None
            if _eidx is not None and _eidx in gpus:
                print(f"[warn] 评测卡 {eval_device} 同时是 actor 卡：异步评测不会阻塞主循环，"
                      f"但会与 actor 抢算力（想完全隔离可换 --eval-device cuda:6/7）",
                      flush=True)
    batch_server = None
    evaluator = None
    if pool is None and args.workers > 1:
        batch_server = BatchLeafServer(model, device=args.device,
                                       batch_size=int(args.batch_size),
                                       max_wait_ms=2.0, queue_size=8192,
                                       norm_mean=norm_mean, norm_std=norm_std)
        evaluator = BatchPPOEvaluator(batch_server)
    elif pool is None:
        evaluator = PPOEvaluator(model, device=args.device,
                                 norm_mean=norm_mean, norm_std=norm_std)

    # ---- 权重版本文件（流水线：worker 在任务开始时按版本懒加载）----
    weights_dir = os.path.join(args.out, "_weights")
    os.makedirs(weights_dir, exist_ok=True)
    published: Dict[str, Any] = {"version": None, "path": None, "history": {}}

    def _publish_weights(version: int) -> str:
        path = os.path.join(weights_dir, f"w_{int(version):06d}.pt")
        tmp = path + ".tmp"
        save_checkpoint(model, tmp, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        os.replace(tmp, path)
        published["version"], published["path"] = int(version), path
        keep = max(2, int(args.keep_versions))
        olds = sorted(glob.glob(os.path.join(weights_dir, "w_*.pt")))
        for old in olds[:-keep]:
            try:
                os.remove(old)
            except OSError:
                pass
        return path

    if pool is not None:
        _publish_weights(int(trainer.updates))

    pipeline_on = bool(int(args.pipeline)) and pool is not None
    if int(args.pipeline) and pool is None:
        print("[warn] --pipeline 需要 --processes>1，已退回串行", flush=True)
    if pipeline_on:
        # 实测：learner 与 actor 共用一张卡时两者互相拖慢（collect +42%、PPO +27%），
        # 流水线整体只快 19%；把 learner 放到独立卡可到 +44%。
        learner_idx = None
        if str(args.device).startswith("cuda"):
            learner_idx = int(str(args.device).split(":")[1]) if ":" in str(args.device) else 0
        actor_gpus = [int(x) for x in str(args.gpus).split(",") if x.strip()]
        if learner_idx is not None and learner_idx in actor_gpus:
            suggest = ",".join(str(g) for g in actor_gpus if g != learner_idx) or "（无其它卡）"
            print(f"[warn] 流水线开启但 learner 与 actor 共用 GPU{learner_idx}："
                  f"实测会互抢（2,552 vs 隔离后 3,100 dec/s）。"
                  f"建议 --gpus {suggest} 或 --device cuda:<空闲卡>。", flush=True)

    def _collect_for(idx: int, wv: Optional[int] = None,
                     wp: Optional[str] = None) -> Tuple[Any, Dict[str, Any], CollectConfig, float]:
        # p ramp：按 iteration 下标求值（空 schedule = 固定 --mirror-p）。
        _mp = float(args.mirror_p)
        if str(args.mirror_p_ramp).strip():
            _mp = float(ramp_p(int(idx), str(args.mirror_p_ramp)))
        c_cfg = CollectConfig(
            games=int(args.games), seed=int(args.seed) + idx * 1000,
            opponent=str(args.opponent), behavior=str(args.behavior),
            max_actions_per_turn=int(args.max_actions_per_turn),
            max_steps=int(args.max_steps), fast_act=bool(int(args.fast_act)),
            lockstep=bool(int(args.lockstep)),
            move_guard=bool(int(args.move_guard)),
            move_cap=int(args.move_cap),
            archetype_bias_coef=float(args.archetype_bias_coef),
            archetype_min_prob=float(args.archetype_min_prob),
            archetype_cache=bool(int(args.archetype_cache)),
            archetype_table=str(args.archetype_table),
            archetype_model=str(args.archetype_model),
            move_repeat_limit=int(args.move_repeat_limit),
            library_pool=str(args.library_pool), library_p=float(args.library_p),
            trajectory_pool=str(args.trajectory_pool), trajectory_p=float(args.trajectory_p),
            mirror_snaps=str(args.mirror_snaps), mirror_seats=int(args.mirror_seats),
            mirror_p=_mp, mirror_sample=str(args.mirror_sample),
            mirror_p_ramp=str(args.mirror_p_ramp),
            mirror_seat_random=bool(int(args.mirror_seat_random)),
            human_boards=str(args.human_boards),
            human_board_p=float(args.human_board_p),
            human_board_seats=int(args.human_board_seats),
            human_board_sample=str(args.human_board_sample),
            human_board_set_tier=bool(int(args.human_board_set_tier)),
            human_board_fidelity=str(args.human_board_fidelity),
            human_board_fast_inject=bool(int(args.human_board_fast_inject)),
            frozen_opponent=str(args.frozen_opponent),
            frozen_seats=int(args.frozen_seats),
            rust_collector=bool(int(args.rust_collector)),
            rc_threads=int(args.rc_threads), leaf_amp=str(args.leaf_amp),
            leaf_compile=bool(int(args.leaf_compile)),
            leaf_wait_ms=float(args.leaf_wait_ms),
            # 动作序列辅助任务：只在启用时让采集/打包侧产出 seq_target（默认 False）
            seq_aux=bool(seq_enabled),
            # 势函数奖励塑形（默认 coef=0 -> 零影响）
            shaping_coef=float(args.shaping_coef),
            shaping_gamma=args.shaping_gamma,
            shaping_w_str=float(args.shaping_w_str),
            shaping_w_tier=float(args.shaping_w_tier),
            shaping_tier_bonus=str(args.shaping_tier_bonus),
            # 等级进度奖励（默认 coef=0 -> 零影响）
            tier_target_coef=float(args.tier_target_coef),
            tier_penalty=float(args.tier_penalty),
            tier_bonus=float(args.tier_bonus),
            tier_target_table=str(args.tier_target_table))
        t_c = time.time()
        if pool is not None:
            batch, collect_meta = pool.collect(
                c_cfg, int(args.games), return_records=True, progress=not pipeline_on,
                seed=int(c_cfg.seed), gamma=float(p_cfg.gamma), lam=float(args.lam),
                weights_version=(published["version"] if wv is None else wv),
                weights_path=(published["path"] if wp is None else wp))
        elif args.workers > 1:
            batch, collect_meta = collect_ppo_batch_parallel(
                model, c_cfg, workers=int(args.workers),
                search_fn=search_fn, search_config=search_cfg,
                eval_fn=evaluator, device=str(args.device),
                seed=int(args.seed) + idx * 1000, gamma=float(p_cfg.gamma),
                lam=float(args.lam),
                norm_mean=norm_mean, norm_std=norm_std, progress=True)
        else:
            batch, collect_meta = collect_ppo_batch(
                model, c_cfg, search_fn=search_fn, search_config=search_cfg,
                eval_fn=evaluator, device=str(args.device),
                seed=int(args.seed) + idx * 1000, gamma=float(p_cfg.gamma),
                lam=float(args.lam),
                norm_mean=norm_mean, norm_std=norm_std, progress=True)
        return batch, collect_meta, c_cfg, time.time() - t_c

    def _pre_ratio(batch: Any, n: int = 2048) -> float:
        """用当前参数对 batch 抽样算 mean ratio（流水线的越策略守卫）。"""
        total = len(batch.actions)
        idx = np.arange(total)
        if total > n:
            idx = np.random.default_rng(0).choice(total, size=n, replace=False)
        dev = torch.device(args.device)
        x = torch.from_numpy(np.ascontiguousarray(batch.features[idx])).to(dev)
        c = torch.from_numpy(np.ascontiguousarray(batch.cards[idx].astype(np.int64))).to(dev)
        m = torch.from_numpy(np.ascontiguousarray(batch.masks[idx].astype(bool))).to(dev)
        a = torch.from_numpy(np.ascontiguousarray(batch.actions[idx].astype(np.int64))).to(dev)
        old = torch.from_numpy(
            np.ascontiguousarray(batch.old_logprobs[idx].astype(np.float32))).to(dev)
        with torch.no_grad():
            logits, _r, _s = split_model_outputs(forward_model(model, x, c, m))
            logp = masked_log_softmax_torch(logits, m).gather(1, a.unsqueeze(1)).squeeze(1)
            ratio = torch.exp(logp - old)
        return float(ratio.mean())

    t0 = time.time()
    deadline = t0 + float(args.minutes) * 60.0
    cum_decisions = 0
    next_eval = (int(args.eval_every_decisions)
                 if int(args.eval_every_decisions) > 0 else 10 ** 18)
    i = int(start_i)
    end_i = (int(start_i) + int(args.iterations)) if int(args.iterations) > 0 else 0
    last_len = 0.0
    executor = ThreadPoolExecutor(max_workers=1) if pipeline_on else None
    pending = None
    if executor is not None:
        pending = executor.submit(_collect_for, i, published["version"], published["path"])
        print(f"[pipeline] on：collect(k+1) 与 update(k) 并行；"
              f"每 batch 版本钉死（lag<=1）；guard={args.pipeline_guard}", flush=True)

    try:
        while time.time() < deadline:
            if end_i > 0 and i >= end_i:
                break
            if float(args.stop_at_decisions) > 0 and cum_decisions >= float(args.stop_at_decisions):
                print(f"[loop] decisions {cum_decisions} >= {int(args.stop_at_decisions)}; stop",
                      flush=True)
                break
            if last_len > 0 and (deadline - time.time()) < max(60.0, last_len):
                print("[loop] remaining time < last iteration; stop", flush=True)
                break
            if eval_stop.is_set():
                # 异步评测结果到达后置 flag：只在下个 iteration 边界停，已完成的 iteration
                # 一定保留（history/snapshot 都已落盘）。
                print(f"[loop] eval stop requested ({eval_state['stop_reason']}); "
                      f"stop at iteration boundary", flush=True)
                if pending is not None:
                    pending.cancel()
                break
            _history_s_prev = locals().get("_history_s", 0.0)
            iter_start = time.time()
            _tl = {"t_iter_start": time.monotonic()}
            _reload_s = 0.0

            if pending is not None:
                batch, collect_meta, c_cfg, _collect_s = pending.result()
                pending = None
            else:
                batch, collect_meta, c_cfg, _collect_s = _collect_for(i)
            _tl["t_collect_done"] = time.monotonic()

            errs = batch.validate()
            if errs:
                print(f"[error] batch invalid: {errs}", file=sys.stderr)
                return 3

            batch_version = int(collect_meta.get("policy_version", -1))
            if batch_version < 0:  # 非 pool 路径
                batch_version = int(trainer.updates)
            lag = int(trainer.updates) - batch_version
            if lag < 0 or lag > 1:
                raise RuntimeError(
                    f"流水线滞后异常：batch_version={batch_version} "
                    f"trainer_version={trainer.updates} lag={lag}（上限 1）")

            # 先发起下一轮采集（用当前已发布权重），再跑 update —— 这是流水的关键顺序
            if executor is not None and (end_i <= 0 or i + 1 < end_i) \
                    and (deadline - time.time()) > 60.0:
                pending = executor.submit(_collect_for, i + 1,
                                          published["version"], published["path"])

            pre_ratio = 1.0
            guard_tripped = False
            if pipeline_on and lag >= 1:
                pre_ratio = _pre_ratio(batch)
                if not (0.8 <= pre_ratio <= 1.25):
                    guard_tripped = True
                    print(f"[pipeline] ratio guard tripped: pre_ratio_mean={pre_ratio:.3f} "
                          f"(lag={lag}); guard={args.pipeline_guard}", flush=True)

            trainer.config.anchor_coef = (
                float(args.anchor_beta) if i < int(args.anchor_iterations)
                else float(args.anchor_beta_tail))
            if seq_enabled:
                # 权重 ramp：按**已累计** decisions 的进度插值（本 iteration 生效）
                trainer.config.seq_coef = float(seq_schedule.coef(cum_decisions))
                if getattr(batch, "seq_target", None) is None and i == start_i:
                    print("[warn] seq 辅助任务已开启但批次没有 seq_target"
                          "（--rust-collector 路径暂不产出标签）-> 本批次 seq_loss=0",
                          flush=True)
            if bc_enabled:
                # BC 系数 ramp：与 seq 同一进度口径（累计 decisions）
                trainer.config.bc_coef = float(bc_schedule.coef(cum_decisions))
            _t_ppo = time.time()
            _tl["t_ppo_start"] = time.monotonic()
            stats = trainer.update(batch)
            # 塑形可观测性：history.jsonl 的 ppo 段带系数与实际 shaping 奖励均值。
            _cmeta = collect_meta.get("collect") if isinstance(collect_meta, dict) else None
            if not isinstance(_cmeta, dict):
                _cmeta = collect_meta if isinstance(collect_meta, dict) else {}
            stats["shaping_coef"] = float(args.shaping_coef)
            stats["shaping_gamma"] = float(shape_gamma)
            stats["shaping_gamma_aligned"] = bool(shape_aligned)
            stats["reward_shaping_mean"] = float(
                _cmeta.get("reward_shaping_mean", 0.0) or 0.0)
            stats["reward_shaping_bias_sum"] = float(
                _cmeta.get("reward_shaping_bias_sum", 0.0) or 0.0)
            # 优势标准差（PPOBatch 已算 advantage_std；history 里此前只有 adv_mean）
            stats["adv_std"] = float(np.std(batch.advantages))
            # 等级进度奖励可观测性（默认关闭时全为 0；history 字段名固定）
            stats["tier_target_coef"] = float(args.tier_target_coef)
            stats["tier_hits"] = int(_cmeta.get("tier_hits", 0) or 0)
            stats["tier_misses"] = int(_cmeta.get("tier_misses", 0) or 0)
            stats["tier_bonus_sum"] = float(_cmeta.get("tier_bonus_sum", 0.0) or 0.0)
            _ppo_s = time.time() - _t_ppo
            _tl["t_ppo_done"] = time.monotonic()

            # 发布新权重（供下一轮 collect 的 *下一次* 使用；lag 恒为 1）
            if pool is not None:
                _publish_weights(int(trainer.updates))

            slim = slim_collect(collect_meta)
            rec = {"iter": i, "collect": slim, "ppo": stats,
                   "pipeline": {"enabled": pipeline_on, "lag": int(lag),
                                "batch_version": int(batch_version),
                                "pre_ratio_mean": round(float(pre_ratio), 4),
                                "guard_tripped": bool(guard_tripped)},
                   "profile": {"reload_s": round(_reload_s, 3),
                               "collect_s": round(_collect_s, 3),
                               "ppo_s": round(_ppo_s, 3),
                               "build_batch_s": round(float(slim.get("build_batch_s", 0.0)), 3),
                               "parent_read_s": round(float(slim.get("parent_read_s", 0.0)), 3),
                               "records_mb": round(float(slim.get("records_bytes", 0)) / 1e6, 1),
                               "history_prev_s": round(float(_history_s_prev), 3)},
                   "batch_server": (dict(batch_server.stats) if batch_server is not None else None),
                   "seconds": time.time() - t0}
            history.append(rec)
            print(f"[iter {i}] ts={time.strftime('%H:%M:%S')} samples={len(batch)} "
                  f"updates={stats['trainer_updates']} "
                  f"lr={stats['lr']:.3g} total={stats['epochs'][-1]['total']:.4f}"
                  + (f" lag={lag} ratio={pre_ratio:.3f}" if pipeline_on else "")
                  + (f" seq={stats.get('seq_loss', 0.0):.4f}"
                     f" seq_coef={stats.get('seq_coef', 0.0):.4g}" if seq_enabled else "")
                  + (f" bc={stats.get('bc_loss', 0.0):.4f}"
                     f" bc_type={stats.get('bc_type_loss', 0.0):.4f}"
                     f" bc_card={stats.get('bc_card_loss', 0.0):.4f}"
                     f" bc_coef={stats.get('bc_coef', 0.0):.4g}"
                     f" bc_samples={stats.get('bc_samples', 0.0):.0f}"
                     if bc_enabled else "")
                  + (f" dpo={stats['dpo_loss']:.4f}"
                     f" dpo_acc={stats['dpo_accept_rate']:.3f}"
                     f" dpo_coef={stats['dpo_coef']:.4g}"
                     f" dpo_n={stats['dpo_samples']:.0f}"
                     if dpo_enabled and "dpo_loss" in stats else "")
                  + (f" pbc={stats['problem_bc_loss']:.4f}"
                     f" pbc_top1={stats.get('problem_bc_top1_acc', 0.0):.3f}"
                     if _problem_enabled and "problem_bc_loss" in stats else "")
                  + (f" saux={stats['strength_aux_loss']:.4f}"
                     f" s_mse={stats.get('strength_mse', 0.0):.4f}"
                     f" s_bce={stats.get('strength_bce', 0.0):.4f}"
                     if _strength_enabled and "strength_aux_loss" in stats else ""),
                  flush=True)

            # 版本化快照：trainer 为权威，model 为导出；manifest 最后原子发布
            ver = int(trainer.updates)
            do_snap = (int(args.snapshot_every) <= 1) or ((i % int(args.snapshot_every)) == 0)
            if do_snap:
                snap = os.path.join(args.out, "snapshots", f"step_{ver:06d}")
                os.makedirs(snap, exist_ok=True)
                trainer.save(os.path.join(snap, "trainer.pt"))
                ckpt = os.path.join(snap, "model.pt")
                tmp_ckpt = ckpt + ".tmp"
                save_checkpoint(model, tmp_ckpt,
                                meta={**meta, "arch": arch, "trainer_updates": ver},
                                norm_mean=norm_mean, norm_std=norm_std)
                os.replace(tmp_ckpt, ckpt)
                trainer.save(os.path.join(args.out, "trainer.pt"))
                ckpt_flat = os.path.join(args.out, "model.pt")
                save_checkpoint(model, ckpt_flat + ".tmp",
                                meta={**meta, "arch": arch, "trainer_updates": ver},
                                norm_mean=norm_mean, norm_std=norm_std)
                os.replace(ckpt_flat + ".tmp", ckpt_flat)
                manifest = {"version": ver, "trainer": os.path.join(snap, "trainer.pt"),
                            "model": os.path.join(snap, "model.pt"),
                            "arch": arch, "seed": int(args.seed),
                            "elapsed_s": time.time() - t0,
                            "history_len": len(history)}
                with open(os.path.join(args.out, "latest.json.tmp"), "w",
                          encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
                os.replace(os.path.join(args.out, "latest.json.tmp"),
                           os.path.join(args.out, "latest.json"))
                keep = int(args.keep_snapshots)
                if keep > 0:
                    snap_root = os.path.join(args.out, "snapshots")
                    olds = sorted(d for d in os.listdir(snap_root)
                                  if d.startswith("step_")
                                  and os.path.isdir(os.path.join(snap_root, d)))
                    for d in olds[:-keep]:
                        shutil.rmtree(os.path.join(snap_root, d), ignore_errors=True)

            # history：追加一行（O(1)），不再全量重写
            _th0 = time.time()
            _tl["t_history_done"] = time.monotonic()
            rec["profile"]["timeline"] = dict(_tl)
            rec["profile"]["collect_timeline"] = slim.get("timeline")
            # history.jsonl 的 eval 段：bot 面板 mean_rank + human 面板
            # human_mean_rank（结果到达后写入后续 iteration；绘图见
            # scripts/plot_quality_curves.py）。
            _eval_seg = _eval_snapshot()
            if _eval_seg:
                rec["eval"] = _eval_seg
            append_record(history_path, to_jsonable(rec))
            _history_s = time.time() - _th0

            cum_decisions += int(slim.get("decisions", 0))
            if cum_decisions >= next_eval:
                if eval_runner is not None:
                    # 异步：只花 ~0.3s 存 ckpt + spawn；评测在 cuda:4 独立跑，主循环继续
                    if not eval_stop.is_set():
                        _submit_eval(cum_decisions)
                else:
                    _run_eval(cum_decisions)
                while next_eval <= cum_decisions:
                    next_eval += int(args.eval_every_decisions)
            last_len = time.time() - iter_start
            i += 1

            if guard_tripped and str(args.pipeline_guard) == "abort":
                save_checkpoint(model, os.path.join(args.out, "model.pt"),
                                meta={**meta, "arch": arch,
                                      "trainer_updates": int(trainer.updates)},
                                norm_mean=norm_mean, norm_std=norm_std)
                print("[pipeline] guard=abort：已保存权重并退出（需要人工检查）", flush=True)
                return 4
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
        if batch_server is not None:
            batch_server.close()
        if pool is not None:
            pool.close()
        if eval_runner is not None:
            # 默认直接终止在跑的评测（不拖 wall）；--eval-drain 1 才等它落 history
            eval_runner.close(drain=bool(int(args.eval_drain)))

    # 收尾：导出最终模型（评测/续训都要用）
    try:
        save_checkpoint(model, os.path.join(args.out, "model.pt"),
                        meta={**meta, "arch": arch,
                              "trainer_updates": int(trainer.updates)},
                        norm_mean=norm_mean, norm_std=norm_std)
        trainer.save(os.path.join(args.out, "trainer.pt"))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] final save failed: {exc!r}", flush=True)
    summary = {"iterations": i, "updates": trainer.updates,
               "elapsed_s": time.time() - t0, "config": vars(args),
               "history_len": len(history),
               "evals": (eval_runner.results_snapshot() if eval_runner is not None
                         else evals),
               "pipeline": {"enabled": pipeline_on,
                            "lag_max_allowed": 1},
               "last_records": history[-5:]}
    if eval_runner is not None:
        summary["eval_async"] = eval_runner.stats()
        summary["evals_skipped"] = list(eval_runner.skipped)
    if eval_state["stop_reason"]:
        summary["eval_stop_reason"] = eval_state["stop_reason"]
    if seq_enabled:
        # 动作序列辅助任务：ramp 终点与累计 decisions（默认关闭时 summary 不变）
        summary["seq"] = {**seq_schedule.describe(),
                          "coef_final": float(seq_schedule.coef(cum_decisions)),
                          "cum_decisions": int(cum_decisions)}
    if bc_enabled:
        summary["bc"] = {
            **bc_schedule.describe(),
            "coef_final": float(bc_schedule.coef(cum_decisions)),
            "cum_decisions": int(cum_decisions),
            "batch": int(args.bc_batch),
            "every": int(args.bc_every),
            "compile": bool(int(args.bc_compile)),
            "type_weight": float(args.bc_type_weight),
            "card_weight": float(args.bc_card_weight),
            "class_weights": dict(bc_class_weights),
            "card_head": bool(bc_card_head),
            "pool": (bc_pool_summary(bc_pool) if bc_pool is not None else None),
        }
    if dpo_enabled:
        # upgrade 子集 DPO：池规模/系数/周期，以及最终 DPO 接受率（=1-选 upgrade 比例）
        summary["dpo"] = {
            "coef": float(args.dpo_coef), "beta": float(args.dpo_beta),
            "batch": int(args.dpo_batch), "every": int(args.dpo_every),
            "samples_path": str(args.dpo_samples),
            "pool_samples": (int(len(dpo_pool)) if dpo_pool is not None else 0),
        }
    write_summary(os.path.join(args.out, "summary.json"), to_jsonable(summary))
    print(f"[done] iters={i} updates={trainer.updates} "
          f"elapsed={time.time()-t0:.0f}s -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
