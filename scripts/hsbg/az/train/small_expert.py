"""小模型专家课程（``SmallExpertCurriculum``）：先在宽经济沙盒学缩放，再逐步加硬限制，
最后放进完整游戏加对手，产出可蒸馏的 ≤5M 小专家。

三阶段（与任务书一致，全部可用 ``--stages`` 选择/续跑）：

- **S1 无约束缩放**：纯经济沙盒（无对手/无战斗），``gold=99`` + 每回合 ``cap=120``，
  奖励 ``L(Σ12) + 0.5·L(Σ15)``（``economy_sandbox --sandbox-reward t12_t15``，逐回合
  密集分解、整局望远镜求和 = 目标）。目标 ``t12 Σ ≥ 1200``。
- **S2 逐步硬限制**：金币 99→30→15→10、每回合动作 120→40→20→10（两维课程）。
  每档在**新约束下**评估，训练到 ``t12`` 相对上一档掉幅 ``<10%`` 才进下一档；
  受预算限制未达标时如实记 ``gate_pass=False`` 后继续。
- **S3 加对手**：完整游戏（Rust 引擎）1→3→5 席人类战团（p=0.3/0.7/0.9），
  奖励 ``0.7·强度 + 0.3·名次``：强度 = ``log_strength`` 势函数塑形（望远镜和
  ``0.7·L(Σ_T)``），名次 = ``--rank-utility-coef 0.3``。

预算：``--max-total-decisions``（默认 8M）按**实际训练决策数**（沙盒/完整游戏 PPO +
BC 采样）累计并在超预算时停在阶段边界。所有子进程的 stdout 落到各自 ``train.log``，
本模块只在 ``curriculum.jsonl / summary.json`` 里记结构化结果。

边界：只读 ``runs/az_entity_*`` 的 checkpoint 作为 BC 教师；所有产物写 ``--out``；
设备默认 ``cuda:7``。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

#: S2 的两维课程（gold, action_cap）：S1 是 (99, 120)，这里从「只压动作」到「只压金币」
#: 再到「两者都压」，避免金币与动作上限同时跳变（历史数据显示每档会塌 ~50%）。
DEFAULT_S2_LEVELS: Tuple[Tuple[int, int], ...] = (
    (99, 40), (30, 40), (15, 20), (10, 10))

#: S3 对手课程（human_board_seats, human_board_p, decisions）
DEFAULT_S3_BANDS: Tuple[Tuple[int, float, int], ...] = (
    (1, 0.30, 100_000), (3, 0.70, 150_000), (5, 0.90, 200_000))

HUMAN_BOARDS = "data/real_library/library_real_quasi_full.jsonl"
S17_CKPT = "runs/az_entity_s17/snapshots/step_001001/model.pt"


def _dump(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _append(path: str, row: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_eval_module() -> Any:
    """加载 ``scripts/train_economy_sandbox.py`` 的 ``evaluate``（沙盒评测唯一口径）。"""
    key = "_hsbg_tes_eval"
    if key in sys.modules:
        return sys.modules[key]
    path = os.path.join(ROOT, "scripts", "train_economy_sandbox.py")
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@dataclass
class CurriculumConfig:
    """课程预算/评测口径（默认值 = 任务书；总预算 ≤ 8M decisions）。"""

    out: str = "runs/small_expert"
    device: str = "cuda:7"
    seed: int = 24100
    #: 小模型架构（与 s14/s17 同编码，权重可回完整游戏）
    d_model: int = 256
    n_layers: int = 4
    #: BC 教师（默认 s17 冻结快照）；空 = 纯 from-scratch
    bc_teacher: str = S17_CKPT
    bc_steps: int = 300_000
    #: 课程起点（小模型热启动）：默认 = 既有 3.57M 沙盒 checkpoint（gold99 下
    #: t12≈1488）。空 = 从零开始（S1 会先用 BC 教师热身）。
    init_checkpoint: str = "runs/economy_sandbox/sb_small/model.pt"
    max_total_decisions: int = 8_000_000
    # ── S1 ──────────────────────────────────────────────────────────────
    s1_gold: int = 99
    s1_cap: int = 120
    s1_steps: int = 250_000
    s1_max_steps: int = 250_000
    s1_chunk: int = 250_000
    s1_gate_t12: float = 1200.0
    # ── S2 ──────────────────────────────────────────────────────────────
    s2_levels: Tuple[Tuple[int, int], ...] = DEFAULT_S2_LEVELS
    s2_chunk: int = 150_000
    s2_max_steps: int = 150_000
    s2_drop_gate: float = 0.10
    # ── S3 ──────────────────────────────────────────────────────────────
    s3_bands: Tuple[Tuple[int, float, int], ...] = DEFAULT_S3_BANDS
    s3_games: int = 24
    s3_processes: int = 4
    s3_threads: int = 4
    s3_lr: float = 3e-6
    s3_strength_coef: float = 0.7
    s3_rank_coef: float = 0.3
    # ── 评测 ────────────────────────────────────────────────────────────
    eval_games: int = 64
    eval_seed_base: int = 900000
    quality_games: int = 48
    quality_seed_base: int = 520000
    stages: str = "s1,s2,s3"

    def as_dict(self) -> Dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}


class SmallExpertCurriculum:
    """三阶段课程驱动（子进程跑训练，本进程只做评测/门控/记账）。"""

    def __init__(self, cfg: Optional[CurriculumConfig] = None) -> None:
        self.cfg = cfg or CurriculumConfig()
        self.cfg.validate() if hasattr(self.cfg, "validate") else None
        os.makedirs(self.cfg.out, exist_ok=True)
        self.spent = 0
        self.rows: List[Dict[str, Any]] = []
        self.ckpt = ""

    # ── 子进程 ──────────────────────────────────────────────────────────
    def _env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [os.path.join(ROOT, "rust", "python"), ROOT] +
            ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env.setdefault("OMP_NUM_THREADS", str(int(self.cfg.s3_threads)))
        env.setdefault("MKL_NUM_THREADS", str(int(self.cfg.s3_threads)))
        # 与其它实验共享 cuda:7：减少显存碎片，避免 OOM（历史坑：batch 16384 在
        # 邻居占 18 GB 时会整批 update 失败，train.log 只有 warn、exit 仍为 0）。
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        return env

    def _run(self, cmd: Sequence[str], log: str) -> int:
        os.makedirs(os.path.dirname(os.path.abspath(log)) or ".", exist_ok=True)
        t0 = time.time()
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"$ {' '.join(cmd)}\n")
            f.flush()
            proc = subprocess.run(cmd, env=self._env(), stdout=f,
                                  stderr=subprocess.STDOUT)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n[exit {proc.returncode}] {time.time() - t0:.1f}s\n")
        self._oom_check(log)
        return int(proc.returncode)

    @staticmethod
    def _oom_check(log: str) -> None:
        """CUDA OOM 会让沙盒训练的 update 全部失败但 exit=0 —— 必须显式失败。"""
        try:
            with open(log, encoding="utf-8", errors="ignore") as f:
                txt = f.read()
        except OSError:
            return
        if "OutOfMemoryError" in txt or "CUDA out of memory" in txt:
            raise RuntimeError(f"CUDA OOM，训练无效（邻居占卡）：{log}")

    # ── 评测：沙盒 ──────────────────────────────────────────────────────
    def eval_sandbox(self, ckpt: str, *, gold: int, cap: int,
                     games: int = 0) -> Dict[str, Any]:
        from hsbg.az.train.economy_sandbox import SandboxConfig
        from hsbg.az.train.model import load_checkpoint
        from hsbg.az.train.ppo import PPOEvaluator
        mod = _load_eval_module()
        # 采样评测用**固定 torch RNG**：`batch_act(sample=True)` 走 torch.multinomial，
        # 不固定的话跨进程/跨调用会抽到不同动作，S2 的 10% 门控会被采样噪声淹没。
        import torch
        torch.manual_seed(int(self.cfg.seed))
        np.random.seed(int(self.cfg.seed))
        model, meta = load_checkpoint(ckpt, device=self.cfg.device)
        cfg = SandboxConfig(
            turns=15, gold_per_turn=int(gold), action_cap=int(cap),
            num_players=8, reward="t12_t15", seed=int(self.cfg.seed))
        ev = mod.evaluate(
            model, cfg, int(games or self.cfg.eval_games), self.cfg.device,
            seed0=int(self.cfg.eval_seed_base), sample=True, dtype="fp32",
            carrier_audit=1)
        del model, meta
        return ev

    # ── 评测：完整游戏（quality_monitor）────────────────────────────────
    def eval_full(self, ckpt: str, *, seats: int, p: float,
                  games: int = 0) -> Dict[str, Any]:
        out = os.path.join(self.cfg.out, f"quality_{os.path.basename(os.path.dirname(ckpt))}"
                                        f"_s{seats}_p{p:.1f}.json")
        cmd = [sys.executable, os.path.join(ROOT, "scripts", "quality_monitor.py"),
               "--checkpoint", ckpt, "--device", self.cfg.device,
               "--games", str(int(games or self.cfg.quality_games)),
               "--seed-base", str(int(self.cfg.quality_seed_base)),
               "--carrier-audit", "1",
               "--human-boards", HUMAN_BOARDS,
               "--human-board-p", str(float(p)),
               "--human-board-seats", str(int(seats)),
               "--human-board-sample", "p75",
               "--human-board-set-tier", "1",
               "--human-board-fidelity", "full",
               "--human-board-fast-inject", "1",
               "--out", out]
        rc = self._run(cmd, out.replace(".json", ".log"))
        if rc != 0 or not os.path.isfile(out):
            return {"error": f"quality_monitor exit={rc}"}
        with open(out, encoding="utf-8") as f:
            q = json.load(f)
        by = {int(r["turn"]): r for r in (q.get("by_turn") or [])}
        return {
            "mean_rank": q.get("mean_rank"), "top4": q.get("top4"),
            "t12_sigma_p50": (by.get(12) or {}).get("ours_p50"),
            "t15_sigma_p50": (by.get(15) or {}).get("ours_p50"),
            "t12_n": (by.get(12) or {}).get("n"),
            "t15_n": (by.get(15) or {}).get("n"),
            "carrier_encounter_rate": q.get("carrier_encounter_rate"),
            "carrier_t9_rate": q.get("carrier_t9_rate"),
            "carrier_t12_rate": q.get("carrier_t12_rate"),
            "carrier_turns_mean": q.get("carrier_turns_mean"),
            "casts_on_carrier_mean": q.get("casts_on_carrier_mean"),
            "survive_t12_ratio": q.get("survive_t12_ratio"),
            "learner_turn_p50": q.get("learner_turn_p50"),
            "path": out,
        }

    # ── 训练子进程：沙盒 / 完整游戏 ─────────────────────────────────────
    def train_sandbox(self, ckpt: str, tag: str, *, gold: int, cap: int,
                      decisions: int, reward: str = "t12_t15",
                      bc_steps: int = 0) -> str:
        seg = os.path.join(self.cfg.out, tag)
        os.makedirs(seg, exist_ok=True)
        cmd = [sys.executable, os.path.join(ROOT, "scripts", "train_economy_sandbox.py"),
               "--checkpoint", ckpt, "--out", seg,
               "--device", self.cfg.device, "--seed", str(int(self.cfg.seed)),
               "--arch", "entity", "--d-model", str(int(self.cfg.d_model)),
               "--n-layers", str(int(self.cfg.n_layers)),
               "--decisions", str(int(decisions)),
               "--envs", "96", "--batch-decisions", "8192",
               "--minibatch", "1024", "--grad-accum", "8", "--epochs", "1",
               "--lr", "3e-6", "--target-kl", "0.05", "--entropy-coef", "0.004",
               "--sandbox-reward", str(reward),
               "--gold-per-turn", str(int(gold)),
               "--sandbox-action-cap-ramp", f"0:{int(cap)}",
               "--action-cap", str(int(cap)),
               "--turns", "15", "--num-players", "8",
               "--eval-every", str(max(250_000, int(decisions) // 4)),
               "--eval-games", "32", "--eval-seed-base", str(int(self.cfg.eval_seed_base)),
               "--save-every", str(int(decisions)), "--bc-epochs", "2",
               "--bc-lr", "1e-4"]
        if bc_steps > 0 and ckpt == "":
            # from-scratch + BC 教师：先把小模型拉到部署策略附近再 PPO
            cmd += ["--from-scratch", "--bc-decisions", str(int(bc_steps)),
                    "--bc-teacher-from", str(self.cfg.bc_teacher)]
        rc = self._run(cmd, os.path.join(seg, "train.log"))
        if rc != 0:
            raise RuntimeError(f"沙盒训练失败 exit={rc}: {seg}/train.log")
        return os.path.join(seg, "model.pt")

    def train_full(self, ckpt: str, tag: str, *, seats: int, p: float,
                   decisions: int) -> str:
        seg = os.path.join(self.cfg.out, tag)
        os.makedirs(seg, exist_ok=True)
        cmd = [sys.executable, os.path.join(ROOT, "scripts", "train_entity_sync.py"),
               "--checkpoint", ckpt, "--out", seg,
               "--device", self.cfg.device, "--gpus", self.cfg.device.split(":")[-1],
               "--gpu-free-check", "0",
               "--processes", str(int(self.cfg.s3_processes)),
               "--threads", str(int(self.cfg.s3_threads)),
               "--games", str(int(self.cfg.s3_games)), "--workers", "1",
               "--arch", "entity", "--opponent", "bot", "--behavior", "net",
               "--sims", "0", "--lockstep", "1", "--fast-act", "1",
               "--epochs", "1", "--minibatch", "1024", "--lr", str(self.cfg.s3_lr),
               "--target-kl", "0.02", "--gamma", "1.0", "--lam", "0.95",
               "--amp", "bf16", "--compile-train", "0",
               "--max-updates", "100000",
               "--stop-at-decisions", str(int(decisions)),
               "--minutes", "240", "--seed", str(int(self.cfg.seed)),
               "--snapshot-every", "100000000", "--keep-snapshots", "1",
               "--eval-every-decisions", "0",
               "--human-boards", HUMAN_BOARDS,
               "--human-board-p", str(float(p)),
               "--human-board-seats", str(int(seats)),
               "--human-board-sample", "p75", "--human-board-set-tier", "1",
               "--human-board-fidelity", "full", "--human-board-fast-inject", "1",
               "--shaping-coef", str(self.cfg.s3_strength_coef),
               "--shaping-mode", "log_strength", "--shaping-w-str", "1.0",
               "--shaping-w-tier", "0",
               "--rank-utility-coef", str(self.cfg.s3_rank_coef),
               "--terminal-strength-coef", str(self.cfg.s3_strength_coef)]
        rc = self._run(cmd, os.path.join(seg, "train.log"))
        if rc != 0:
            raise RuntimeError(f"完整游戏训练失败 exit={rc}: {seg}/train.log")
        # train_entity_sync 的收尾权重：<out>/model.pt（_atomic_torch_save）
        return os.path.join(seg, "model.pt")

    # ── 记账 ────────────────────────────────────────────────────────────
    def _spend(self, n: int) -> None:
        self.spent += int(n)

    def _log(self, row: Dict[str, Any]) -> None:
        row = dict(row)
        row["spent"] = int(self.spent)
        row["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.rows.append(row)
        _append(os.path.join(self.cfg.out, "curriculum.jsonl"), row)
        print(f"[curr] {json.dumps({k: row.get(k) for k in row if k != 't'}, ensure_ascii=False)}",
              flush=True)

    def _budget_ok(self, need: int, *, margin: int = 0) -> bool:
        return int(self.spent) + int(need) + int(margin) <= int(self.cfg.max_total_decisions)

    # ── 主流程 ──────────────────────────────────────────────────────────
    def run(self, stages: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        stages = [str(s) for s in (stages or self.cfg.stages.split(",")) if s]
        t0 = time.time()
        # 起点：优先复用已有 final 权重（可断点续跑）；全新 run 从 from-scratch + BC 开始
        resume = os.path.join(self.cfg.out, "model.pt")
        ckpt = resume if os.path.isfile(resume) else ""
        if not ckpt and self.cfg.init_checkpoint and \
                os.path.isfile(str(self.cfg.init_checkpoint)):
            ckpt = str(self.cfg.init_checkpoint)
        if "s1" in stages:
            ckpt = self._run_s1(ckpt)
        if "s2" in stages:
            ckpt = self._run_s2(ckpt)
        if "s3" in stages:
            ckpt = self._run_s3(ckpt)
        final = os.path.join(self.cfg.out, "model.pt")
        if ckpt and os.path.abspath(ckpt) != os.path.abspath(final):
            import shutil
            shutil.copy2(ckpt, final)
        summary = {"config": self.cfg.as_dict(), "spent": int(self.spent),
                   "final_checkpoint": final, "rows": self.rows,
                   "seconds": round(time.time() - t0, 1)}
        _dump(os.path.join(self.cfg.out, "summary.json"), summary)
        return summary

    def _run_s1(self, ckpt: str) -> str:
        cfg = self.cfg
        need = int(cfg.s1_max_steps)
        bc = int(cfg.bc_steps) if not ckpt else 0
        if not self._budget_ok(need + bc):
            self._log({"stage": "S1", "event": "skipped_budget"})
            return ckpt
        stage_ckpt = ckpt
        if ckpt:
            ev0 = self.eval_sandbox(ckpt, gold=cfg.s1_gold, cap=cfg.s1_cap)
            self._log({"stage": "S1", "event": "entry", "decisions": 0,
                       "gold": cfg.s1_gold, "action_cap": cfg.s1_cap,
                       "reward": "t12_t15", "checkpoint": ckpt,
                       "t12": ev0.get("sigma_t12_p50"),
                       "t15": ev0.get("sigma_t15_p50"),
                       "carrier_rate": ev0.get("carrier_rate"),
                       "casts_on_carrier": ev0.get("casts_on_carrier_mean"),
                       "tier_dist": ev0.get("tier_dist")})
        n = 0
        while n < need:
            chunk = int(min(cfg.s1_chunk, need - n))
            tag = f"s1_{n // max(chunk, 1):02d}"
            stage_ckpt = self.train_sandbox(
                stage_ckpt if n > 0 else (ckpt or ""), tag,
                gold=cfg.s1_gold, cap=cfg.s1_cap, decisions=chunk,
                bc_steps=(bc if n == 0 else 0))
            self._spend(chunk + (bc if n == 0 else 0))
            n += chunk
            ev = self.eval_sandbox(stage_ckpt, gold=cfg.s1_gold, cap=cfg.s1_cap)
            self._log({"stage": "S1", "event": "eval", "decisions": n,
                       "gold": cfg.s1_gold, "action_cap": cfg.s1_cap,
                       "reward": "t12_t15", "checkpoint": stage_ckpt,
                       "t12": ev.get("sigma_t12_p50"), "t15": ev.get("sigma_t15_p50"),
                       "t12_p90": ev.get("sigma_t12_p90"),
                       "carrier_rate": ev.get("carrier_rate"),
                       "casts_on_carrier": ev.get("casts_on_carrier_mean"),
                       "tier_dist": ev.get("tier_dist"),
                       "spells_p50": ev.get("spells_p50")})
            if float(ev.get("sigma_t12_p50") or 0.0) >= float(cfg.s1_gate_t12):
                self._log({"stage": "S1", "event": "gate_pass",
                           "t12": ev.get("sigma_t12_p50")})
                break
        return stage_ckpt

    def _run_s2(self, ckpt: str) -> str:
        cfg = self.cfg
        prev_t12: Optional[float] = None
        # 上一档（S1）的 t12 作为第一个 S2 档的参照
        try:
            ev0 = self.eval_sandbox(ckpt, gold=cfg.s1_gold, cap=cfg.s1_cap)
            prev_t12 = float(ev0.get("sigma_t12_p50") or 0.0)
        except Exception:  # noqa: BLE001 - 参照缺失时只做档内报告
            prev_t12 = None
        for li, (gold, cap) in enumerate(cfg.s2_levels):
            entry = self.eval_sandbox(ckpt, gold=gold, cap=cap)
            entry_t12 = float(entry.get("sigma_t12_p50") or 0.0)
            ref = float(prev_t12 if prev_t12 is not None else entry_t12) or 1.0
            self._log({"stage": "S2", "event": "entry", "level": li,
                       "gold": gold, "action_cap": cap,
                       "t12": entry_t12, "t15": entry.get("sigma_t15_p50"),
                       "carrier_rate": entry.get("carrier_rate"),
                       "casts_on_carrier": entry.get("casts_on_carrier_mean"),
                       "ref_t12": ref,
                       "drop": round(1.0 - entry_t12 / ref, 4)})
            n = 0
            gate = False
            t12 = entry_t12
            while n < int(cfg.s2_max_steps):
                if not self._budget_ok(int(cfg.s2_chunk)):
                    break
                tag = f"s2_l{li}_{n // max(int(cfg.s2_chunk), 1):02d}"
                ckpt = self.train_sandbox(ckpt, tag, gold=gold, cap=cap,
                                          decisions=int(cfg.s2_chunk))
                self._spend(int(cfg.s2_chunk))
                n += int(cfg.s2_chunk)
                ev = self.eval_sandbox(ckpt, gold=gold, cap=cap)
                t12 = float(ev.get("sigma_t12_p50") or 0.0)
                drop = 1.0 - t12 / ref
                self._log({"stage": "S2", "event": "eval", "level": li,
                           "gold": gold, "action_cap": cap, "decisions": n,
                           "checkpoint": ckpt, "t12": t12,
                           "t15": ev.get("sigma_t15_p50"),
                           "carrier_rate": ev.get("carrier_rate"),
                           "casts_on_carrier": ev.get("casts_on_carrier_mean"),
                           "tier_dist": ev.get("tier_dist"),
                           "ref_t12": ref, "drop": round(drop, 4),
                           "gate_pass": bool(drop <= float(cfg.s2_drop_gate))})
                if drop <= float(cfg.s2_drop_gate):
                    gate = True
                    break
            prev_t12 = float(t12)
            self._log({"stage": "S2", "event": "level_done", "level": li,
                       "gold": gold, "action_cap": cap, "trained": n,
                       "gate_pass": bool(gate), "t12": prev_t12})
        return ckpt

    def _run_s3(self, ckpt: str) -> str:
        cfg = self.cfg
        for bi, (seats, p, decisions) in enumerate(cfg.s3_bands):
            if not self._budget_ok(int(decisions)):
                self._log({"stage": "S3", "event": "skipped_budget",
                           "band": bi, "seats": seats, "p": p})
                continue
            tag = f"s3_b{bi}_seats{seats}_p{p:.1f}"
            ckpt = self.train_full(ckpt, tag, seats=int(seats), p=float(p),
                                   decisions=int(decisions))
            self._spend(int(decisions))
            ev = self.eval_full(ckpt, seats=int(seats), p=float(p))
            self._log({"stage": "S3", "event": "eval", "band": bi,
                       "seats": seats, "p": p, "decisions": int(decisions),
                       "checkpoint": ckpt, **ev})
        return ckpt

    # ── 单点评测（断点续跑/报告用）───────────────────────────────────────
    def evaluate_all(self, ckpt: str) -> Dict[str, Any]:
        """在 S1/S2 全部约束 + S3 全部对手档上评测一个 checkpoint。"""
        out: Dict[str, Any] = {"checkpoint": ckpt, "sandbox": {}, "full": {}}
        for gold, cap in [(self.cfg.s1_gold, self.cfg.s1_cap)] + list(self.cfg.s2_levels):
            key = f"gold{gold}_cap{cap}"
            ev = self.eval_sandbox(ckpt, gold=gold, cap=cap)
            out["sandbox"][key] = {k: ev.get(k) for k in
                                   ("sigma_t12_p50", "sigma_t15_p50",
                                    "carrier_rate", "casts_on_carrier_mean",
                                    "tier_dist", "spells_p50")}
        for seats, p, _d in self.cfg.s3_bands:
            key = f"seats{seats}_p{p:.1f}"
            out["full"][key] = self.eval_full(ckpt, seats=int(seats), p=float(p))
        return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="小模型专家课程（S1/S2/S3）")
    ap.add_argument("--out", default="runs/small_expert")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--seed", type=int, default=24100)
    ap.add_argument("--stages", default="s1,s2,s3")
    ap.add_argument("--max-total-decisions", type=int, default=8_000_000)
    ap.add_argument("--bc-teacher", default=S17_CKPT)
    ap.add_argument("--bc-steps", type=int, default=300_000)
    ap.add_argument("--init-checkpoint", default="runs/economy_sandbox/sb_small/model.pt",
                    help="课程起点小模型（空=from scratch + BC）")
    ap.add_argument("--budget-steps", type=int, default=0,
                    help="每档训练决策预算（覆盖 S2 的 chunk/max；0=用默认值）")
    ap.add_argument("--s1-steps", type=int, default=250_000)
    ap.add_argument("--s1-max-steps", type=int, default=250_000)
    ap.add_argument("--s2-chunk", type=int, default=250_000)
    ap.add_argument("--s2-max-steps", type=int, default=500_000)
    ap.add_argument("--s3-strength-coef", type=float, default=0.7)
    ap.add_argument("--s3-rank-coef", type=float, default=0.3)
    ap.add_argument("--s3-games", type=int, default=24)
    ap.add_argument("--s3-processes", type=int, default=4)
    ap.add_argument("--s3-threads", type=int, default=4)
    ap.add_argument("--eval-games", type=int, default=64)
    ap.add_argument("--quality-games", type=int, default=48)
    ap.add_argument("--eval-only", default="", help="只评测该 checkpoint 并退出")
    args = ap.parse_args(argv)
    cfg = CurriculumConfig(
        out=str(args.out), device=str(args.device), seed=int(args.seed),
        bc_teacher=str(args.bc_teacher), bc_steps=int(args.bc_steps),
        init_checkpoint=str(args.init_checkpoint),
        max_total_decisions=int(args.max_total_decisions),
        s1_steps=int(args.s1_steps), s1_max_steps=int(args.s1_max_steps),
        s2_chunk=int(args.budget_steps or args.s2_chunk),
        s2_max_steps=int(args.budget_steps or args.s2_max_steps),
        s3_strength_coef=float(args.s3_strength_coef),
        s3_rank_coef=float(args.s3_rank_coef),
        s3_games=int(args.s3_games), s3_processes=int(args.s3_processes),
        s3_threads=int(args.s3_threads), eval_games=int(args.eval_games),
        quality_games=int(args.quality_games), stages=str(args.stages))
    cur = SmallExpertCurriculum(cfg)
    if str(args.eval_only):
        rep = cur.evaluate_all(str(args.eval_only))
        _dump(os.path.join(cfg.out, "eval_all.json"), rep)
        print(json.dumps(rep, ensure_ascii=False, indent=2)[:4000])
        return 0
    summ = cur.run()
    print(json.dumps({k: summ[k] for k in ("spent", "final_checkpoint", "seconds")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
