"""无 PyTorch 环境下的最小策略/价值网络（numpy MLP + 手写梯度）。

用于远程机 torch 安装失败/不可用时的训练管线 smoke；接口与 `std_net.AZNet`
的 evaluator 对齐（features 3227 → 245 policy + 8 rank）。训练用 Adam。
"""

from __future__ import annotations

import numpy as np

N_ACTIONS = 245
N_PLAYERS = 8
OBS_FLOATS = 3227
UTILITY = np.array([1.0 - 2.0 * (r - 1) / (N_PLAYERS - 1) for r in range(1, N_PLAYERS + 1)],
                   dtype=np.float32)


def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


class NumpyAZNet:
    def __init__(self, in_dim: int = OBS_FLOATS, hidden: int = 128, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.W1 = (rng.standard_normal((in_dim, hidden)) * np.sqrt(2.0 / in_dim)).astype(np.float32)
        self.b1 = np.zeros(hidden, np.float32)
        self.W2 = (rng.standard_normal((hidden, N_ACTIONS)) * np.sqrt(2.0 / hidden)).astype(np.float32)
        self.b2 = np.zeros(N_ACTIONS, np.float32)
        self.Wv = (rng.standard_normal((hidden, N_PLAYERS)) * np.sqrt(2.0 / hidden)).astype(np.float32)
        self.bv = np.zeros(N_PLAYERS, np.float32)
        self.params = ("W1", "b1", "W2", "b2", "Wv", "bv")

    def forward(self, x: np.ndarray):
        z1 = x @ self.W1 + self.b1
        h = np.maximum(z1, 0.0)
        logits = h @ self.W2 + self.b2
        vlog = h @ self.Wv + self.bv
        return z1, h, logits, vlog

    def predict_one(self, features: np.ndarray, mask: np.ndarray):
        x = np.asarray(features, dtype=np.float32)[None, :]
        _, _, logits, vlog = self.forward(x)
        probs = softmax(logits)[0]
        m = np.asarray(mask, dtype=bool)
        probs[~m] = 0.0
        s = probs.sum()
        probs = probs / s if s > 0 else m.astype(np.float32) / max(m.sum(), 1)
        value = float((softmax(vlog)[0] * UTILITY).sum())
        return probs.astype(np.float32), value

    def train_step(self, X, pi, rank, opt_state, lr: float = 3e-4, beta1=0.9, beta2=0.999,
                   eps=1e-8, t: int = 1):
        z1, h, logits, vlog = self.forward(X)
        p = softmax(logits)
        pv = softmax(vlog)
        B = X.shape[0]
        # policy CE with masked target pi (already masked); gradient p - pi
        dlogits = (p - pi) / B
        onehot = np.zeros((B, N_PLAYERS), np.float32)
        onehot[np.arange(B), np.maximum(rank - 1, 0)] = 1.0
        dvlog = (pv - onehot) / B
        dW2 = h.T @ dlogits
        db2 = dlogits.sum(axis=0)
        dWv = h.T @ dvlog
        dbv = dvlog.sum(axis=0)
        dh = dlogits @ self.W2.T + dvlog @ self.Wv.T
        dz1 = dh * (z1 > 0)
        dW1 = X.T @ dz1
        db1 = dz1.sum(axis=0)
        grads = {"W1": dW1, "b1": db1, "W2": dW2, "b2": db2, "Wv": dWv, "bv": dbv}
        for k in self.params:
            g = grads[k]
            m = opt_state["m"][k]
            v = opt_state["v"][k]
            m[...] = beta1 * m + (1 - beta1) * g
            v[...] = beta2 * v + (1 - beta2) * (g * g)
            mhat = m / (1 - beta1 ** t)
            vhat = v / (1 - beta2 ** t)
            getattr(self, k)[...] -= lr * mhat / (np.sqrt(vhat) + eps)
        loss = -float((pi * np.log(np.maximum(p, 1e-12))).sum(axis=1).mean()) \
            - float(np.log(np.maximum(pv[np.arange(B), np.maximum(rank - 1, 0)], 1e-12)).mean())
        return loss

    def init_opt(self):
        return {"m": {k: np.zeros_like(getattr(self, k)) for k in self.params},
                "v": {k: np.zeros_like(getattr(self, k)) for k in self.params}}

    def save(self, path: str):
        np.savez(path, **{k: getattr(self, k) for k in self.params})

    @classmethod
    def load(cls, path: str):
        z = np.load(path)
        n = cls.__new__(cls)
        for k in z.files:
            setattr(n, k, z[k])
        n.params = tuple(z.files)
        return n


def make_evaluator(net: NumpyAZNet):
    def evaluator(features, cards, mask, seat: int = 0):
        return net.predict_one(features, mask)
    return evaluator
