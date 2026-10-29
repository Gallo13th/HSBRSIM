"""轻量 AZ 策略/价值网络（初期 smoke 用，不追求规模）。

结构：3227 features -> LayerNorm -> MLP(hidden) -> {policy head 245, rank head 8}。
- 策略头：245 logits（训练用 masked softmax + 软目标 CE）；
- 名次头：8 logits（rank CE），价值 = ``E_{r~softmax}[u(r)]`` ∈ [-1,1]；
- cards（124 个卡牌下标）初期不编码（仅 features），后续可加 embedding；
- 输入标准化参数（mean/std）随 checkpoint 保存，推理复用同一口径。

torch 为可选依赖：本模块 import 时**不**导入 torch，``TinyAZNet`` 需要时再加载，
保证无 torch 环境也能使用``common``/``data``/``report`` 等引擎无关组件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .common import N_ACTIONS, N_RANKS, OBS_FLOATS, RANK_UTILITY, masked_normalize


def _torch():
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("torch 不可用：训练路径需要 `pip install torch`") from exc
    return torch


def _default_bc_card_dim() -> int:
    """卡牌身份头输出维度（惰性读卡表；默认 37.0.0 = 3983）。"""
    from .bc_aux import bc_card_head_size
    return int(bc_card_head_size())


def bc_card_head_dim(model: Any) -> int:
    """模型 trunk 的输出维度（tiny=policy_head.in_features；entity=d_model）。"""
    if hasattr(model, "d_model"):
        return int(model.d_model)
    if hasattr(model, "policy_head"):
        return int(model.policy_head.in_features)
    raise ValueError("无法推断模型 trunk 维度：既无 d_model 也无 policy_head")


def attach_bc_card_head(model: Any, dim: Optional[int] = None) -> Any:
    """给已有模型**追加**（或复用）卡牌身份头，返回同一模型。

    用于「从旧 checkpoint 续训 + ``bc_coef>0``」：旧 ckpt 没有 ``card_head``，加载后
    在这里新建一个（正态初始化，随后的 BC 梯度训练它）。``dim`` 默认 3983（卡表条目数）。
    幂等：已有 ``card_head`` 时直接返回。
    """
    torch = _torch()
    nn = torch.nn
    if getattr(model, "card_head", None) is not None:
        return model
    n = int(dim) if dim is not None else _default_bc_card_dim()
    d = bc_card_head_dim(model)
    model.card_head = nn.Linear(d, n)
    # 与 build_net 一致：零初始化 = 初始均匀先验（CE=ln(n_cards)）
    nn.init.zeros_(model.card_head.weight)
    nn.init.zeros_(model.card_head.bias)
    try:
        model.bc_card_dim = n
    except Exception:  # noqa: BLE001 - 非 nn.Module 的测试替身忽略
        pass
    return model


if True:  # 命名空间占位：TinyAZNet 在下方用 torch.nn 定义（需要 torch 时惰性加载）
    pass


def build_net(hidden: int = 256, *, arch: str = "tiny", obs_floats: int = OBS_FLOATS,
              n_actions: int = N_ACTIONS, n_ranks: int = N_RANKS,
              seq_head: bool = False, bc_card_head: bool = False,
              bc_card_dim: Optional[int] = None, **kwargs):
    """构造策略网络：tiny（MLP）或 entity（AutoTavern 风格实体 Transformer）。

    ``seq_head=True`` 时额外构建「动作序列辅助头」（trunk -> 245 logits，
    ``docs/ACTION_SEQUENCE_AUX.md``）；**默认 False = 不构建**，因此默认路径的参数量、
    前向与 checkpoint 与之前完全一致。

    ``bc_card_head=True`` 时额外构建「卡牌身份头」（trunk -> ``bc_card_dim`` 类，
    默认 = 卡表条目数 3983；``docs/BC_AUX.md`` 分层 BC）。**默认 False =
    不构建**：``bc_coef=0`` 时模型参数/前向/checkpoint 与旧版本逐位一致。
    """
    if arch == "entity":
        from .entity_model import build_entity_net
        kwargs["seq_head"] = bool(seq_head)
        kwargs["bc_card_head"] = bool(bc_card_head)
        if bc_card_dim is not None:
            kwargs["bc_card_dim"] = int(bc_card_dim)
        return build_entity_net(**kwargs)
    if arch == "entity18m":
        from .entity_model import build_entity_net
        kwargs.setdefault("dim_ff", 2048)
        kwargs.setdefault("n_extra_tokens", 8)
        kwargs.setdefault("pos_size", 24)
        kwargs.setdefault("arch", "entity18m")
        kwargs["seq_head"] = bool(seq_head)
        kwargs["bc_card_head"] = bool(bc_card_head)
        if bc_card_dim is not None:
            kwargs["bc_card_dim"] = int(bc_card_dim)
        return build_entity_net(**kwargs)
    torch = _torch()
    nn = torch.nn
    card_dim = int(bc_card_dim) if bc_card_dim is not None else 0
    if bc_card_head and card_dim <= 0:
        card_dim = int(_default_bc_card_dim())

    class TinyAZNet(nn.Module):
        """3227 -> hidden -> {245 policy logits, 8 rank logits[, 245 seq logits]}。"""

        def __init__(self) -> None:
            super().__init__()
            self.obs_floats = int(obs_floats)
            self.n_actions = int(n_actions)
            self.n_ranks = int(n_ranks)
            self.norm = nn.LayerNorm(self.obs_floats)
            self.trunk = nn.Sequential(
                nn.Linear(self.obs_floats, int(hidden)), nn.ReLU(),
                nn.Linear(int(hidden), int(hidden)), nn.ReLU(),
            )
            self.policy_head = nn.Linear(int(hidden), self.n_actions)
            self.rank_head = nn.Linear(int(hidden), self.n_ranks)
            # 动作序列辅助头（turn 内动作 multi-hot）：默认 None = 不构建、不计算
            self.seq_head = nn.Linear(int(hidden), self.n_actions) if seq_head else None
            # 卡牌身份头（分层 BC）：默认 None = 不构建、参数/checkpoint 不变
            self.card_head = (nn.Linear(int(hidden), int(card_dim))
                              if bc_card_head else None)
            if self.card_head is not None:
                # 零初始化 = 初始均匀先验：card CE 起点 = ln(3983)，梯度稳定
                nn.init.zeros_(self.card_head.weight)
                nn.init.zeros_(self.card_head.bias)
            self.bc_card_dim = int(card_dim) if bc_card_head else 0

        def forward(self, features, cards=None):  # cards 暂不编码（保留接口）
            x = self.norm(features)
            h = self.trunk(x)
            return self.policy_head(h), self.rank_head(h)

        def forward_aux(self, features, cards=None, mask=None):
            """``(logits, rank_logits, None, seq_logits|None)``（tiny 无标量 value 头）。

            只有 ``seq_head`` 被构建（``build_net(..., seq_head=True)``）时最后一项非 None；
            其余调用方仍用 ``forward()``，行为完全不变。
            """
            x = self.norm(features)
            h = self.trunk(x)
            seq = None if self.seq_head is None else self.seq_head(h)
            return self.policy_head(h), self.rank_head(h), None, seq

        def forward_bc(self, features, cards=None, mask=None):
            """分层 BC 用的一次前向：``(policy_logits, card_logits|None)``。

            只在 ``bc_coef>0`` 的 BC 分支调用；未建 ``card_head`` 时第二项为 None
            （此时只有类型级 CE）。默认路径完全不调用本方法。
            """
            x = self.norm(features)
            h = self.trunk(x)
            card = None if self.card_head is None else self.card_head(h)
            return self.policy_head(h), card

    return TinyAZNet()


class NetEvaluator:
    """把网络包装成搜索评估器：``(prior[245], value)``。

    ``mask=None`` 时按全合法处理（BatchEnv 批量前向时由调用方负责）。
    """

    def __init__(self, model: Any, device: str = "cpu",
                 norm_mean: Optional[np.ndarray] = None,
                 norm_std: Optional[np.ndarray] = None) -> None:
        self.torch = _torch()
        self.model = model
        self.device = self.torch.device(device)
        self.model.to(self.device)
        self.model.eval()
        self.mean = None if norm_mean is None else np.asarray(norm_mean, dtype=np.float32)
        self.std = None if norm_std is None else np.asarray(norm_std, dtype=np.float32)

    def _normalize(self, f: np.ndarray) -> np.ndarray:
        x = np.asarray(f, dtype=np.float32)
        if self.mean is not None:
            x = x - self.mean
        if self.std is not None:
            x = x / self.std
        return x

    def logits(self, features: np.ndarray, cards: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
        """批量前向：features [B,3227] (+cards) -> (policy_logits, rank_logits)。"""
        torch = self.torch
        x = self._normalize(np.atleast_2d(features))
        with torch.no_grad():
            t = torch.from_numpy(np.ascontiguousarray(x)).to(self.device)
            if getattr(self.model, "uses_cards", False):
                if cards is None:
                    cards = np.zeros((t.shape[0], 124), dtype=np.int64)
                card_t = torch.from_numpy(np.ascontiguousarray(
                    np.atleast_2d(cards).astype(np.int64))).to(self.device)
                out = self.model(t, card_t)
            else:
                out = self.model(t)
        return out[0].detach().cpu().numpy(), out[1].detach().cpu().numpy()

    def value_from_rank_logits(self, rank_logits: np.ndarray) -> np.ndarray:
        z = np.asarray(rank_logits, dtype=np.float64)
        z = z - z.max(axis=-1, keepdims=True)
        p = np.exp(z)
        p = p / p.sum(axis=-1, keepdims=True)
        return (p * RANK_UTILITY.astype(np.float64)).sum(axis=-1).astype(np.float32)

    def __call__(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                 seat: int = 0) -> tuple[np.ndarray, float]:
        plog, rlog = self.logits(features, cards)
        m = None if mask is None else np.asarray(mask, dtype=bool).reshape(-1)
        prior = plog[0]
        pi = masked_normalize(prior, m) if m is not None else _softmax(prior)
        value = float(self.value_from_rank_logits(rlog[0]))
        return pi.astype(np.float32), value


def _softmax(logits: np.ndarray) -> np.ndarray:
    z = np.asarray(logits, dtype=np.float64)
    z = z - z.max()
    e = np.exp(z)
    return (e / e.sum()).astype(np.float32)


# ── 输入标准化统计（从数据估计，随 checkpoint 保存）────────────────────
def feature_stats(features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """计算特征 mean/std（std 下限 1e-3，避免除零）。"""
    x = np.asarray(features, dtype=np.float64)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std < 1e-3, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


# ── checkpoint ───────────────────────────────────────────────────────────
@dataclass
class Meta:
    """训练元信息（随 checkpoint 保存，保证可复现/跨版本可比）。"""

    hidden: int = 256
    epochs: int = 0
    samples: int = 0
    data_version: str = ""
    engine_version: str = ""
    policy_kind: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d.update(d.pop("extra", {}) or {})
        return d


def save_checkpoint(model: Any, path: str, *, meta: Optional[Dict[str, Any]] = None,
                    norm_mean: Optional[np.ndarray] = None,
                    norm_std: Optional[np.ndarray] = None) -> str:
    """保存 torch checkpoint（含标准化统计与 meta）。返回路径。"""
    torch = _torch()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    payload: Dict[str, Any] = {"state_dict": model.state_dict(), "meta": dict(meta or {})}
    if norm_mean is not None:
        payload["norm_mean"] = [float(v) for v in np.asarray(norm_mean, dtype=np.float32).tolist()]
    if norm_std is not None:
        payload["norm_std"] = [float(v) for v in np.asarray(norm_std, dtype=np.float32).tolist()]
    payload["meta"].setdefault("arch", getattr(model, "arch", "tiny"))
    # 动作序列辅助头：有无随 checkpoint 保存，load 时据此重建（默认 False = 旧 checkpoint）
    payload["meta"].setdefault("seq_head", bool(getattr(model, "seq_head", None) is not None))
    # 卡牌身份头（分层 BC）：默认 False = 不建、旧 checkpoint 逐位一致
    _card_head = getattr(model, "card_head", None)
    payload["meta"].setdefault("bc_card_head", bool(_card_head is not None))
    if _card_head is not None:
        payload["meta"].setdefault("bc_card_dim", int(_card_head.out_features))
    if hasattr(model, "d_model"):
        payload["meta"].setdefault("d_model", int(model.d_model))
        payload["meta"].setdefault("n_layers", int(getattr(model.trunk, "num_layers", 8)))
        payload["meta"].setdefault("n_heads", int(getattr(model.trunk.layers[0], "nhead", 8))
                                  if hasattr(model.trunk, "layers") else 8)
    if hasattr(model, "obs_floats"):
        payload["meta"].setdefault("obs_floats", int(model.obs_floats))
        payload["meta"].setdefault("n_actions", int(model.n_actions))
        payload["meta"].setdefault("n_ranks", int(model.n_ranks))
    torch.save(payload, path)
    return path


def load_checkpoint(path: str, device: str = "cpu") -> tuple[Any, Dict[str, Any]]:
    """加载 checkpoint -> (model, meta)；meta 含标准化统计（norm_mean/norm_std）。"""
    torch = _torch()
    # 只加载自己训练产出的 checkpoint；norm 统计以 list 存储，weights_only=True 可加载。
    try:
        payload = torch.load(path, map_location=device, weights_only=True)
    except TypeError:  # torch < 2.0 无 weights_only 形参
        payload = torch.load(path, map_location=device)
    meta = dict(payload.get("meta") or {})
    hidden = int(meta.get("hidden", 256))
    arch = str(meta.get("arch", "tiny"))
    seq_head = bool(meta.get("seq_head", False))
    # 卡牌身份头（分层 BC）：meta 声明或 state_dict 里确有 card_head.* 都重建
    state = payload.get("state_dict") or {}
    has_card_head = bool(meta.get("bc_card_head", False)) or any(
        str(k).startswith("card_head.") for k in state)
    card_dim = int(meta.get("bc_card_dim", 0) or 0)
    if arch == "entity18m":
        model = build_net(arch="entity18m", seq_head=seq_head,
                          bc_card_head=has_card_head,
                          bc_card_dim=(card_dim or None))
    elif arch == "entity":
        model = build_net(arch="entity", d_model=int(meta.get("d_model", 384)),
                          n_layers=int(meta.get("n_layers", 8)),
                          n_heads=int(meta.get("n_heads", 8)),
                          seq_head=seq_head, bc_card_head=has_card_head,
                          bc_card_dim=(card_dim or None))
    else:
        model = build_net(hidden, seq_head=seq_head, bc_card_head=has_card_head,
                          bc_card_dim=(card_dim or None))
    model.load_state_dict(payload["state_dict"])
    model.to(torch.device(device))
    model.eval()
    if "norm_mean" in payload:
        meta["norm_mean"] = np.asarray(payload["norm_mean"], dtype=np.float32)
    if "norm_std" in payload:
        meta["norm_std"] = np.asarray(payload["norm_std"], dtype=np.float32)
    return model, meta


__all__ = [
    "build_net",
    "attach_bc_card_head",
    "bc_card_head_dim",
    "NetEvaluator",
    "feature_stats",
    "Meta",
    "save_checkpoint",
    "load_checkpoint",
]
