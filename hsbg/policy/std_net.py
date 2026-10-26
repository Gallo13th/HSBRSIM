"""固定 245 动作 / 3227 观测的最小策略-价值网络（pipeline smoke 用）。

这不是最终网络：卡片块暂未编码（只使用 features），隐藏层很小；用于验证
“obs → 245 policy + 8 rank value”的数据/训练闭环。后续替换为完整编码器。
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

N_ACTIONS = 245
N_PLAYERS = 8
OBS_FLOATS = 3227
UTILITY = torch.tensor([1.0 - 2.0 * (r - 1) / (N_PLAYERS - 1) for r in range(1, N_PLAYERS + 1)],
                       dtype=torch.float32)


class AZNet(nn.Module):
    def __init__(self, in_dim: int = OBS_FLOATS, hidden: int = 256):
        super().__init__()
        self.in_norm = nn.LayerNorm(in_dim)
        self.trunk = nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(),
                                   nn.Linear(hidden, hidden), nn.ReLU())
        self.policy = nn.Linear(hidden, N_ACTIONS)
        self.value = nn.Linear(hidden, N_PLAYERS)

    def forward(self, x: torch.Tensor):
        h = self.trunk(self.in_norm(x))
        return self.policy(h), self.value(h)


def make_evaluator(net: AZNet, device: str = "cpu"):
    """返回 evaluator(features, cards, mask, seat) -> (policy_probs[np245], value float)."""
    net.eval()

    @torch.no_grad()
    def evaluator(features: np.ndarray, cards, mask, seat: int = 0):
        x = torch.from_numpy(np.asarray(features, dtype=np.float32)).to(device).unsqueeze(0)
        logits, vlog = net(x)
        logits = logits[0].float()
        probs = torch.softmax(logits, dim=-1).cpu().numpy().astype(np.float32)
        m = np.asarray(mask, dtype=bool)
        probs[~m] = 0.0
        s = probs.sum()
        probs = probs / s if s > 0 else m.astype(np.float32) / max(m.sum(), 1)
        vprobs = torch.softmax(vlog[0].float(), dim=-1)
        value = float((vprobs.cpu() * UTILITY).sum().item())
        return probs, value

    return evaluator


def save_checkpoint(net: AZNet, path: str, meta: dict | None = None):
    torch.save({"state_dict": net.state_dict(), "config": {"in_dim": OBS_FLOATS,
                "hidden": net.trunk[0].out_features}, "meta": meta or {}}, path)


def load_checkpoint(path: str, device: str = "cpu") -> AZNet:
    blob = torch.load(path, map_location=device, weights_only=False)
    cfg = blob.get("config", {})
    net = AZNet(in_dim=int(cfg.get("in_dim", OBS_FLOATS)),
                hidden=int(cfg.get("hidden", 256))).to(device)
    net.load_state_dict(blob["state_dict"])
    net.eval()
    return net
