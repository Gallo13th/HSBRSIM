"""Warband encoder / value network trained on pairwise combat outcomes.

Input features (padded to 7 slots):
  cards (B,7) int, atk/hp (B,7) float, tier (B,7) float,
  keywords (B,7,K) float, lengths (B,) int

Output: scalar strength s.  Pairwise Bradley-Terry: P(A beats B)=sigmoid(sA-sB).
Also returns the CLS embedding for downstream composition embedding use.
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn


class WarbandEncoder(nn.Module):
    def __init__(self, n_cards: int, n_keywords: int, *, dim: int = 128,
                 layers: int = 3, heads: int = 4, max_len: int = 7,
                 dropout: float = 0.1) -> None:
        super().__init__()
        self.dim = dim
        self.max_len = max_len
        self.card = nn.Embedding(n_cards + 1, 32, padding_idx=0)
        self.pos = nn.Embedding(max_len + 1, dim)
        self.tier = nn.Embedding(8, 16)
        self.stat = nn.Sequential(nn.Linear(2, 32), nn.SiLU(), nn.Linear(32, 32))
        self.kw = nn.Sequential(nn.Linear(n_keywords, 32), nn.SiLU())
        self.proj = nn.Sequential(
            nn.Linear(32 + 32 + 16 + 32, dim), nn.SiLU(), nn.Linear(dim, dim)
        )
        self.cls = nn.Parameter(torch.zeros(1, 1, dim))
        layer = nn.TransformerEncoderLayer(
            d_model=dim, nhead=heads, dim_feedforward=dim * 2,
            dropout=dropout, batch_first=True, activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=layers)
        self.norm = nn.LayerNorm(dim)
        self.head = nn.Sequential(
            nn.Linear(dim, dim), nn.SiLU(), nn.Dropout(dropout), nn.Linear(dim, 1)
        )

    def forward(self, cards: torch.Tensor, atk: torch.Tensor, hp: torch.Tensor,
                tier: torch.Tensor, kw: torch.Tensor, lengths: torch.Tensor):
        b, n = cards.shape
        mask = torch.arange(n, device=cards.device)[None, :] < lengths[:, None]
        pos = torch.arange(n, device=cards.device)
        tok = self.proj(torch.cat([
            self.card(cards),
            self.stat(torch.stack([torch.log1p(atk.clamp_min(0)),
                                   torch.log1p(hp.clamp_min(0))], -1)),
            self.tier(tier.clamp(0, 7).long()),
            self.kw(kw),
        ], dim=-1)) + self.pos(pos)[None, :, :]
        cls = self.cls.expand(b, -1, -1)
        seq = torch.cat([cls, tok], dim=1)
        cls_mask = torch.zeros((b, 1), dtype=torch.bool, device=cards.device)
        pad_mask = torch.cat([cls_mask, ~mask], dim=1)  # True = ignore
        out = self.encoder(seq, src_key_padding_mask=pad_mask)
        z = self.norm(out[:, 0])
        s = self.head(z).squeeze(-1)
        return s, z


def pairwise_loss(s_a: torch.Tensor, s_b: torch.Tensor, win: torch.Tensor,
                  *, margin: float = 0.0) -> torch.Tensor:
    """BCE on soft win-rate targets (0/0.5/1 or empirical win rate)."""
    logit = s_a - s_b
    if margin > 0:
        target = (win > 0.5).float()
        return torch.nn.functional.softplus(-(logit - margin) * (2 * target - 1)).mean()
    return torch.nn.functional.binary_cross_entropy_with_logits(logit, win)
