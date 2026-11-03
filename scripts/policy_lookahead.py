"""潜力引导的 1 步前瞻策略（推理期，不改训练）。

在 t>=min_turn 的决策点：取模型 top-k 合法动作 → 逐个在 game.copy() 上模拟一步 →
用 10 维特征过 logistic p(Σ15>=3.5k) → 选 max Δp 的动作；若 Δp<=0 退回模型 top-1。
"""
from __future__ import annotations
import json, os, sys
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "rust", "python"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

CHAIN = {"BG21_015": 0, "BG29_813": 1, "BG36_245": 2, "BG36_640": 3}


def _load_logit(path: str):
    d = np.load(path)
    return (d["w"].astype(np.float64), float(d["b"]),
            d["mu"].astype(np.float64), d["sd"].astype(np.float64))


def _cards_db() -> Dict[str, Dict[str, Any]]:
    d = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("cards") or d.get("data") or list(d.values())
    return {str(c["id"]): c for c in d if isinstance(c, dict) and c.get("id")}


class LookaheadPolicy:
    def __init__(self, inner, logit_path: str = "data/scaling_value/logit.npz",
                 k: int = 4, min_turn: int = 7) -> None:
        self.inner = inner
        self.k = int(k)
        self.min_turn = int(min_turn)
        self.w, self.b, self.mu, self.sd = _load_logit(os.path.join(ROOT, logit_path))
        self.cards = _cards_db()
        self.retention = set()
        for cid, c in self.cards.items():
            t = int(c.get("tier") or 0)
            tx = str(c.get("text") or "").lower()
            if 4 <= t <= 6 and (cid in CHAIN or "permanently keep" in tx
                                or "double" in tx or "twice" in tx):
                self.retention.add(cid)
        self.stats = {"decisions": 0, "lookahead": 0, "dp_positive": 0, "ms": 0.0}

    def reset(self) -> None:
        try:
            self.inner.reset()
        except BaseException:  # noqa: BLE001
            pass

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _feat(self, g) -> np.ndarray:
        import hsbg_engine as E  # noqa: PLC0415
        cid2id = getattr(self, "_cid2id", None)
        if cid2id is None:
            cid2id = {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}
            self._cid2id = cid2id
        pj = json.loads(g.player_json(0))
        board = [cid2id.get(int(m.get("card") or -1), "") for m in (pj.get("board") or [])]
        sig = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in (pj.get("board") or []))
        golds = sum(1 for m in (pj.get("board") or []) if m.get("golden"))
        races = set()
        for c in board:
            d = self.cards.get(c[:-2] if c.endswith("_G") else c) or {}
            for r in (d.get("races") or []):
                races.add(str(r))
        ret = sum(1 for c in board if (c[:-2] if c.endswith("_G") else c) in self.retention)
        hand_n = len([x for x in (pj.get("hand") or [])])
        return np.asarray([float(g.turn), float(pj.get("gold") or 0), float(pj.get("tier") or 0),
                           float(np.log1p(sig)), float(len(pj.get("board") or [])), float(golds),
                           float(len(races)), float(ret), float(hand_n),
                           float(pj.get("health") or 0)], dtype=np.float64)

    def _p(self, g) -> float:
        x = self._feat(g)
        return float(1.0 / (1.0 + np.exp(-(((x - self.mu) / self.sd) @ self.w + self.b))))

    def decide(self, game, seat: int = 0):
        import time as _t
        from hsbg.az.train.ppo import mask_from_bytes  # noqa: PLC0415
        t0 = _t.time()
        dec = self.inner.decide(game, seat)
        self.stats["decisions"] += 1
        turn = int(game.turn)
        if turn < self.min_turn:
            return dec
        mask = mask_from_bytes(game.legal_mask(seat))
        nz = np.flatnonzero(mask)
        if nz.size <= 1:
            return dec
        base = int(dec.action)
        # 取模型 top-k：用 inner 的分布不可得时，退化为"top-1 + 若干高价值动作"（买/升级/刷新）
        cand = [base]
        prio = [8, 9, 10, 11, 12, 13, 14, 15, 3, 1]
        for a in prio:
            if len(cand) >= self.k:
                break
            if a in nz and a not in cand:
                cand.append(int(a))
        p0 = self._p(game)
        best, best_dp = base, 0.0
        try:
            for a in cand:
                if a == base:
                    continue
                g2 = game.copy()
                g2.step(int(seat), int(a))
                p1 = self._p(g2)
                dp = p1 - p0
                if dp > best_dp:
                    best, best_dp = int(a), float(dp)
        except BaseException:  # noqa: BLE001
            best = base
        self.stats["lookahead"] += 1
        if best_dp > 0:
            self.stats["dp_positive"] += 1
        self.stats["ms"] += (_t.time() - t0) * 1000.0
        try:
            return type(dec)(action=best, pi=getattr(dec, "pi", None),
                             info=dict(getattr(dec, "info", {}) or {}))
        except BaseException:  # noqa: BLE001
            return dec
