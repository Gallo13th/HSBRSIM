"""学习评估器：BC 策略/价值 → 候选 prior + placement utility。

复用现有资产（不新增训练）：
- ``runs/bc/official_320/policy_bc.pt``（1.24M entity Transformer，rank 分布价值头）；
- ``ObservationEncoder``（39 entity slots / candidate_max=64）；
- ``forward_full`` → masked policy logits + rank_logits + value(E[rank]→utility)。

Phase 1 只做推理；不训练、不改 checkpoint。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch

from hsbg.env import observation
from hsbg.env.spec import CandidateAction
from hsbg.policy.model import load_policy_and_encoder
from hsbg.search.forward import EngineForwardModel
from hsbg.search.types import StateEval, prior_softmax

__all__ = ["PolicyEvaluator", "DEFAULT_BC_CHECKPOINT"]

DEFAULT_BC_CHECKPOINT = "runs/bc/official_320/policy_bc.pt"


@dataclass
class PolicyEvaluator:
    """BC checkpoint 推理封装；``evaluate`` 返回 state 的 prior/value。"""

    checkpoint: str = DEFAULT_BC_CHECKPOINT
    device: str = "cpu"
    prior_temperature: float = 1.0

    def __post_init__(self) -> None:
        pol, enc = load_policy_and_encoder(self.checkpoint)
        self.policy = pol
        self.encoder = enc
        self.policy.eval()
        if self.device and self.device != "cpu":
            self.policy = self.policy.to(self.device)
        self._device = torch.device(self.device)
        with torch.no_grad():
            self._dummy = None

    # ── 基础 ──
    def _batch_to_device(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in batch.items():
            if isinstance(v, torch.Tensor):
                out[k] = v.to(self._device)
            else:
                out[k] = v
        return out

    def evaluate(self, model: EngineForwardModel) -> StateEval:
        """评估当前 state；终局直接返回 placement utility。"""
        if model.is_terminal():
            rank = model.rank()
            u = model.terminal_utility()
            probs = np.zeros(model.total_players, dtype=np.float64)
            if 1 <= rank <= model.total_players:
                probs[rank - 1] = 1.0
            return StateEval(
                candidates=(), prior=np.zeros(0), value=float(u),
                expected_rank=float(rank), rank_probs=probs, obs=None,
            )

        model.drain_choices()
        candidates = model.candidates()
        if not candidates:
            return StateEval(candidates=(), prior=np.zeros(0), value=-1.0,
                             expected_rank=float(model.total_players),
                             rank_probs=np.zeros(model.total_players))
        obs = observation.build_observation(
            model.game, model.hero, candidates,
            phase="recruit", turn=model.turn,
            total_players=model.total_players,
            extra=None,
        )
        batch = self._batch_to_device(self.encoder.collate([obs]))
        with torch.no_grad():
            out = self.policy.forward_full(batch)
        n = len(candidates)
        logits = out["logits"][0, :n].detach().cpu().numpy().astype(np.float64)
        mask = None
        if "cand_mask" in batch:
            mask = batch["cand_mask"][0, :n].detach().cpu().numpy().astype(bool)
        prior = prior_softmax(logits, temperature=self.prior_temperature, mask=mask)
        value = float(out["value"][0].detach().cpu())
        rank_probs = torch.softmax(out["rank_logits"][0], dim=-1).detach().cpu().numpy()
        expected_rank = float(out["expected_rank"][0].detach().cpu())
        return StateEval(
            candidates=candidates, prior=prior, value=value,
            expected_rank=expected_rank, rank_probs=rank_probs, obs=obs,
        )

    # ── 便捷：搜索对比用 ──
    def top_action(self, model: EngineForwardModel
                   ) -> Optional[Tuple[CandidateAction, float]]:
        ev = self.evaluate(model)
        if not ev.candidates or ev.prior.size == 0:
            return None
        i = int(np.argmax(ev.prior))
        return ev.candidates[i], float(ev.prior[i])

    def value(self, model: EngineForwardModel) -> float:
        return float(self.evaluate(model).value)

    # ── 批量价值（turn-search 状态打分；冻结推理） ──
    def value_batch(self, models: List[EngineForwardModel]) -> Dict[str, np.ndarray]:
        """对一个状态列表做 batch value 前向；返回 value/expected_rank/rank_probs。

        只用于排序/评分，不训练、不更新权重。终局/无候选状态单独回退。
        """
        n = len(models)
        total_players = int(getattr(models[0], "total_players", 8)) if n else 8
        values = np.zeros(n, dtype=np.float64)
        expected = np.zeros(n, dtype=np.float64)
        probs = np.zeros((n, total_players), dtype=np.float64)
        obs_list = []
        idx_obs: List[int] = []
        for i, model in enumerate(models):
            if model.is_terminal():
                rank = model.rank()
                values[i] = float(model.terminal_utility())
                expected[i] = float(rank)
                if 1 <= rank <= probs.shape[1]:
                    probs[i, rank - 1] = 1.0
                continue
            try:
                model.drain_choices()
                cands = model.candidates()
                if not cands:
                    values[i] = -1.0
                    expected[i] = float(model.total_players)
                    continue
                obs = observation.build_observation(
                    model.game, model.hero, cands, phase="recruit",
                    turn=model.turn, total_players=model.total_players,
                    extra=None)
                obs_list.append(obs)
                idx_obs.append(i)
            except Exception:  # noqa: BLE001
                values[i] = -1.0
                expected[i] = float(model.total_players)
        if obs_list:
            batch = self._batch_to_device(self.encoder.collate(obs_list))
            with torch.no_grad():
                out = self.policy.forward_full(batch)
            vals = out["value"].detach().cpu().numpy().astype(np.float64)
            er = out["expected_rank"].detach().cpu().numpy().astype(np.float64)
            rp = torch.softmax(out["rank_logits"], dim=-1).detach().cpu().numpy()
            for k, i in enumerate(idx_obs):
                values[i] = float(vals[k])
                expected[i] = float(er[k])
                probs[i, :rp.shape[1]] = rp[k]
        return {"value": values, "expected_rank": expected,
                "rank_probs": probs}
