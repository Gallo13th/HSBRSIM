"""Oilcan / 升本折扣饰品先验 + s22 模型 A/B（不改 compound_script.py）。

A. `TeacherPrior(CompoundPolicy)`：饰品 pending 时，若 `tier < 6` 且选项里有升本折扣饰品，
   按 `BG30_MagicItem_705`（Oilcan，-3/回合）> `BG36_MagicItem_300`（刷新 -1）> 其它 的
   优先级强制选择；否则交给基策略。
B. `ModelPrior`：s22 checkpoint 的沙盒策略（batch_act）+ 同一饰品先验。
C. 同 seed 对照：teacher base vs prior（12 局）；model base vs prior（24 局）。
   报 Oilcan/300 出现率与选择率、tier@t15、S15 p50。

用法：
    python scripts/oilcan_prior_probe.py --teacher-games 12 --model-games 24 \
        --checkpoint runs/az_entity_s22_ctrl/model.pt --device cpu
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
import sys
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    EconomySandbox, SandboxConfig, stack_obs)
from train_economy_sandbox import batch_act  # noqa: E402
from compound_script import CompoundPolicy  # noqa: E402

A_CHOOSE = 30
#: 升本折扣饰品优先级（高 → 低）
UPGRADE_TRINKETS = ["BG30_MagicItem_705", "BG36_MagicItem_300"]


def _trinket_choice(v: dict, mask: np.ndarray) -> Optional[int]:
    """若当前是 trinket pending 且有升本折扣饰品 → 返回 Choose action。"""
    me = v.get("me") or {}
    pend = me.get("pending")
    if not isinstance(pend, dict) or str(pend.get("kind")) != "trinket":
        return None
    if int(me.get("tier") or 0) >= 6:
        return None
    opts = [str(o.get("id") or "") for o in (pend.get("options") or [])]
    for want in UPGRADE_TRINKETS:
        if want in opts:
            j = opts.index(want)
            a = A_CHOOSE + j
            if a < A_CHOOSE + 16 and bool(mask[a]):
                return int(a)
    return None


class TeacherPrior(CompoundPolicy):
    """CompoundPolicy + 升本折扣饰品先验。"""

    def act(self, v: dict, mask: np.ndarray) -> int:
        me = v.get("me") or {}
        if not me.get("pending") and str(v.get("phase")) == "recruit":
            a = _trinket_choice(v, mask)
            if a is not None:
                return a
        return int(super().act(v, mask))


class ModelPrior:
    """s22 checkpoint 沙盒策略；`prior=True` 时启用同一个饰品先验。"""

    def __init__(self, model: Any, device: str, *, prior: bool = True,
                 sample: bool = True, seed: int = 0) -> None:
        self.model = model
        self.device = device
        self.prior = bool(prior)
        self.sample = bool(sample)
        self.rng = np.random.default_rng(seed)

    def act(self, env: EconomySandbox, obs: Any, v: dict, mask: np.ndarray) -> int:
        if self.prior:
            a = _trinket_choice(v, mask)
            if a is not None:
                return a
        f, c, m = stack_obs([obs])
        a, _lp, _val = batch_act(self.model, f, c, m, self.device,
                                 sample=self.sample, dtype="fp32")
        return int(a[0])


def _load_model(path: str, device: str = "cpu") -> Any:
    from hsbg.az.train.model import load_checkpoint
    model, _meta = load_checkpoint(path, device=device)
    model.eval()
    return model


def _run_games(cfg: SandboxConfig, games: int, seed0: int, kind: str,
               model: Any = None, device: str = "cpu", prior: bool = False) -> Dict[str, Any]:
    offers = 0
    up_offers = collections.Counter()
    up_picks = collections.Counter()
    tiers: List[int] = []
    s15s: List[int] = []
    offers_detail: List[Dict[str, Any]] = []
    for gi in range(games):
        seed = seed0 + gi
        env = EconomySandbox(cfg)
        obs = env.reset(seed)
        if kind == "teacher":
            pol: Any = TeacherPrior(seed=seed) if prior else CompoundPolicy(seed=seed)
        else:
            pol = ModelPrior(model, device, prior=prior, seed=seed)
        while not env.done:
            v = json.loads(env.g.view(0))
            a = (pol.act(v, obs.mask) if kind == "teacher"
                 else pol.act(env, obs, v, obs.mask))
            was_trinket = False
            opts: List[str] = []
            me = v.get("me") or {}
            pend = me.get("pending")
            if isinstance(pend, dict) and str(pend.get("kind")) == "trinket":
                was_trinket = True
                opts = [str(o.get("id") or "") for o in (pend.get("options") or [])]
            obs, _r, _d, _info = env.step(int(a))
            if was_trinket and opts:
                offers += 1
                for cid in UPGRADE_TRINKETS:
                    if cid in opts:
                        up_offers[cid] += 1
                if A_CHOOSE <= int(a) < A_CHOOSE + 16:
                    j = int(a) - A_CHOOSE
                    sel = opts[j] if j < len(opts) else ""
                    for cid in UPGRADE_TRINKETS:
                        if sel == cid:
                            up_picks[cid] += 1
                offers_detail.append({"game": gi, "options": opts,
                                      "picked": (opts[int(a) - A_CHOOSE]
                                                 if A_CHOOSE <= int(a) < A_CHOOSE + 16
                                                 and int(a) - A_CHOOSE < len(opts) else "")})
        ep = env.episode_summary()
        p = json.loads(env.g.player_json(0))
        tiers.append(int(p.get("tier") or 0))
        s15s.append(int(ep.get("sigma_t15") or 0))
    out = {"kind": kind, "prior": prior, "games": games, "offers": offers,
           "upgrade": {}}
    for cid in UPGRADE_TRINKETS:
        out["upgrade"][cid] = {
            "offers": up_offers[cid],
            "offer_rate": round(up_offers[cid] / max(1, offers), 3),
            "picks": up_picks[cid],
            "pick_rate_when_offered": round(up_picks[cid] / max(1, up_offers[cid]), 3),
        }
    out["tier_t15_mean"] = round(float(statistics.mean(tiers)), 2) if tiers else 0
    out["tier_t15_p50"] = float(np.percentile(tiers, 50)) if tiers else 0
    out["sigma_t15_p50"] = float(np.percentile(s15s, 50)) if s15s else 0
    out["sigma_t15_mean"] = round(float(statistics.mean(s15s)), 1) if s15s else 0
    out["offers_detail"] = offers_detail
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Oilcan trinket prior + s22 A/B")
    ap.add_argument("--teacher-games", type=int, default=12)
    ap.add_argument("--model-games", type=int, default=24)
    ap.add_argument("--checkpoint", default=os.path.join(
        ROOT, "runs", "az_entity_s22_ctrl", "model.pt"))
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--gold-per-turn", type=int, default=30)
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "sandbox_econ",
                                                       "oilcan_prior.json"))
    args = ap.parse_args(argv)
    cfg = SandboxConfig(turns=15, gold_mode="fixed", gold_per_turn=int(args.gold_per_turn),
                        action_cap=40, num_players=8, trinkets=True, gold_cap=99,
                        lobby_types=())
    out: Dict[str, Any] = {"config": {"gold_per_turn": args.gold_per_turn,
                                      "checkpoint": args.checkpoint,
                                      "seed0": args.seed0}, "arms": {}}
    out["arms"]["teacher_base"] = _run_games(cfg, args.teacher_games,
                                             args.seed0, "teacher", prior=False)
    out["arms"]["teacher_prior"] = _run_games(cfg, args.teacher_games,
                                              args.seed0, "teacher", prior=True)
    model = _load_model(args.checkpoint, args.device)
    out["arms"]["model_base"] = _run_games(cfg, args.model_games, args.seed0, "model",
                                           model=model, device=args.device, prior=False)
    out["arms"]["model_prior"] = _run_games(cfg, args.model_games, args.seed0, "model",
                                            model=model, device=args.device, prior=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, r in out["arms"].items():
        u = r["upgrade"]["BG30_MagicItem_705"]
        print(f"{k:14s} games={r['games']:2d} offers={r['offers']:2d} "
              f"oilcan_offers={u['offers']:2d} picks={u['picks']} "
              f"pick_rate={u['pick_rate_when_offered']:.2f} "
              f"tier_p50={r['tier_t15_p50']:.0f} S15p50={r['sigma_t15_p50']:.0f}",
              flush=True)
    print(f"WROTE {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
