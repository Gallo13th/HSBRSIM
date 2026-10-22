"""实体 Transformer 策略网络（候选动作打分 + 名次分布价值头）。

结构
----
::

    EntityToken ── card_emb ─┐
                              ├─► + zone_emb + pos_emb + num_mlp ─┐
    Global ───── global_mlp ──┴─► CLS token ────────────────────┴─► Transformer ×L
                                                                        │
              ┌─────────────────────────────────────────────────────────┤
              ▼                                                         ▼
    candidates: kind_emb + src/tgt 实体表示 + cand_num_mlp          价值头
                + 全局表示 ─► MLP ─► logit[B,C]        mean/max-pool + CLS ─► 名次 logits
                masked softmax                                             → E[rank] → value

设计要点
--------
* **候选独立打分**：候选动作集合是变长的，直接对每个候选打分再做 masked
  softmax；候选引用 ``src/tgt`` 的实体表示，天然支持指针式目标选择。
* **分布价值**：输出 ``num_players`` 个名次 logits，``E[rank]`` 映射到
  ``[-1, 1]`` 的标量 value 供 GAE 使用；终局用名次交叉熵额外训练分布。
* **checkpoint 自包含**：config + 词表 + 编码器尺寸 + 版本一起保存，
  ``load`` 后可直接 ``make_encoder()`` 复现推理。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from hsbg.env.spec import NUM_ACTION_KINDS, PLAYER_MAX
from hsbg.policy.encoder import (
    CAND_FEATURE_OFFSET,
    ENCODER_DIMS,
    MAX_ZONE_SLOTS,
    NUM_ENTITIES,
    EncoderDims,
    ObservationEncoder,
    PAD_CARD_INDEX,
    CardVocab,
)

#: checkpoint 格式版本（结构不兼容时 +1）
CHECKPOINT_FORMAT_VERSION = 1
#: 掩码 logit 的下界（有限值，避免 -inf 造成 NaN 梯度）
MASKED_LOGIT = -1e9


# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════


@dataclass
class PolicyConfig:
    """网络超参（全部写进 checkpoint，``load`` 时重建同构网络）。"""

    # ── 网络宽度 ──
    dim: int = 128
    layers: int = 4
    heads: int = 4
    ff_dim: int = 256
    dropout: float = 0.0
    # ── 词表 / 编码尺寸（构建时按实际词表与编码器填入）──
    vocab_size: int = len(CardVocab())
    num_entities: int = NUM_ENTITIES
    entity_num_dim: int = ENCODER_DIMS.entity_num_dim
    global_dim: int = ENCODER_DIMS.global_dim
    cand_num_dim: int = ENCODER_DIMS.cand_num_dim
    candidate_max: int = ENCODER_DIMS.candidate_max
    num_zones: int = ENCODER_DIMS.num_zones
    max_zone_slots: int = MAX_ZONE_SLOTS
    # ── 动作 / 价值 ──
    num_action_kinds: int = NUM_ACTION_KINDS
    num_players: int = PLAYER_MAX
    #: ``"distribution"``：名次分布头；``"scalar"``：单标量头
    value_mode: str = "distribution"

    # ── 校验 ──
    def __post_init__(self) -> None:
        if self.dim % self.heads != 0:
            raise ValueError(f"dim({self.dim}) 必须能被 heads({self.heads}) 整除")
        if self.value_mode not in ("distribution", "scalar"):
            raise ValueError(f"未知 value_mode: {self.value_mode}")
        if self.num_players < 2:
            raise ValueError("num_players 必须 >= 2")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PolicyConfig":
        allowed = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**allowed)

    @classmethod
    def for_encoder(
        cls,
        encoder: Union[ObservationEncoder, EncoderDims],
        *,
        vocab_size: Optional[int] = None,
        **overrides: Any,
    ) -> "PolicyConfig":
        """按编码器实际尺寸生成配置（避免手写维度漂移）。"""
        if isinstance(encoder, ObservationEncoder):
            dims = encoder.dims
            vocab_size = len(encoder.vocab) if vocab_size is None else vocab_size
        else:
            dims = encoder
        return cls(
            vocab_size=int(vocab_size or len(CardVocab())),
            num_entities=dims.num_entities,
            entity_num_dim=dims.entity_num_dim,
            global_dim=dims.global_dim,
            cand_num_dim=dims.cand_num_dim,
            candidate_max=dims.candidate_max,
            num_zones=dims.num_zones,
            **overrides,
        )

    def encoder_dims(self) -> EncoderDims:
        return EncoderDims(
            num_entities=self.num_entities,
            entity_num_dim=self.entity_num_dim,
            global_dim=self.global_dim,
            cand_num_dim=self.cand_num_dim,
            candidate_max=self.candidate_max,
            num_zones=self.num_zones,
        )


# ══════════════════════════════════════════════════════════════════════
# 网络
# ══════════════════════════════════════════════════════════════════════


class EntityTransformerPolicy(nn.Module):
    """实体 Transformer + 候选动作打分 + 名次分布价值。"""

    def __init__(self, config: Optional[PolicyConfig] = None) -> None:
        super().__init__()
        self.config = config or PolicyConfig()
        cfg = self.config
        d = cfg.dim

        # ── 实体输入 ──
        self.card_emb = nn.Embedding(cfg.vocab_size, d, padding_idx=PAD_CARD_INDEX)
        self.entity_num_mlp = nn.Sequential(
            nn.Linear(cfg.entity_num_dim, d),
            nn.ReLU(),
            nn.Linear(d, d),
        )
        self.zone_emb = nn.Embedding(cfg.num_zones, d)
        self.pos_emb = nn.Embedding(cfg.max_zone_slots + 1, d)
        #: 全局表示作为 CLS token 注入序列
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d))
        nn.init.normal_(self.cls_token, std=0.02)
        self.global_mlp = nn.Sequential(
            nn.Linear(cfg.global_dim, d),
            nn.ReLU(),
            nn.Linear(d, d),
        )
        self.input_norm = nn.LayerNorm(d)

        # ── Transformer ──
        layer = nn.TransformerEncoderLayer(
            d_model=d,
            nhead=cfg.heads,
            dim_feedforward=cfg.ff_dim,
            dropout=cfg.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            layer, num_layers=cfg.layers, norm=nn.LayerNorm(d), enable_nested_tensor=False
        )

        # ── 候选动作打分 ──
        self.kind_emb = nn.Embedding(cfg.num_action_kinds, d)
        self.src_proj = nn.Linear(d, d)
        self.tgt_proj = nn.Linear(d, d)
        self.cand_num_mlp = nn.Sequential(
            nn.Linear(cfg.cand_num_dim, d),
            nn.ReLU(),
            nn.Linear(d, d),
        )
        self.cand_combine = nn.Sequential(
            nn.Linear(d, d),
            nn.ReLU(),
        )
        self.score_head = nn.Sequential(
            nn.Linear(2 * d, d),
            nn.ReLU(),
            nn.Linear(d, 1),
        )

        # ── 价值头（名次分布）──
        self.value_combiner = nn.Sequential(
            nn.Linear(3 * d, d),
            nn.ReLU(),
        )
        self.value_trunk = nn.Sequential(
            nn.Linear(d, d),
            nn.ReLU(),
        )
        self.rank_head = nn.Linear(d, cfg.num_players)
        self.scalar_head = nn.Linear(d, 1)
        #: 名次张量（1..num_players），非持久 buffer
        self.register_buffer(
            "_ranks",
            torch.arange(1, cfg.num_players + 1, dtype=torch.float32),
            persistent=False,
        )

        #: checkpoint 里保存的词表 / 编码器元信息（load 后可用于推理）
        self.vocab: Optional[CardVocab] = None
        self.encoder_dims: EncoderDims = cfg.encoder_dims()
        self.meta: Dict[str, Any] = {}
        self.checkpoint_path: Optional[str] = None

    # ── 前向 ──
    def _encode_state(self, batch: Dict[str, torch.Tensor]) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """返回 ``(cls_rep, entity_reps, entity_mask)``。"""
        cfg = self.config
        card = batch["entity_card"].long().clamp(0, cfg.vocab_size - 1)
        mask = batch["entity_mask"].float()
        zone = batch["entity_zone"].long().clamp(0, cfg.num_zones - 1)
        pos = batch["entity_pos"].long().clamp(0, cfg.max_zone_slots)
        ent = (
            self.card_emb(card)
            + self.entity_num_mlp(batch["entity_num"])
            + self.zone_emb(zone)
            + self.pos_emb(pos)
        )
        # padding 实体输入置零（mask 之外不参与 attention，但表示要干净）
        ent = ent * mask.unsqueeze(-1)
        cls = self.cls_token.expand(card.shape[0], -1, -1) + self.global_mlp(
            batch["global"]
        ).unsqueeze(1)
        seq = torch.cat([cls, ent], dim=1)
        seq = self.input_norm(seq)
        valid = torch.cat(
            [torch.ones(mask.shape[0], 1, device=mask.device), mask], dim=1
        ).bool()
        out = self.transformer(seq, src_key_padding_mask=~valid)
        return out[:, 0, :], out[:, 1:, :], mask

    def _pool_entities(self, ent: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """masked mean + masked max 池化。"""
        m = mask.unsqueeze(-1)
        count = m.sum(dim=1).clamp_min(1.0)
        mean = (ent * m).sum(dim=1) / count
        has = m.sum(dim=1) > 0
        neg = torch.full_like(ent, -1e9)
        vmax = torch.where(m.bool(), ent, neg).max(dim=1).values
        vmax = torch.where(has, vmax, torch.zeros_like(vmax))
        return torch.cat([mean, vmax], dim=-1)

    def _value_from_rank_logits(self, rank_logits: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """名次 logits → (value ∈ [-1,1], E[rank])。"""
        cfg = self.config
        probs = F.softmax(rank_logits, dim=-1)
        expected_rank = (probs * self._ranks).sum(dim=-1)
        scale = float(cfg.num_players - 1)
        value = (cfg.num_players + 1.0 - 2.0 * expected_rank) / scale
        return value, expected_rank

    def forward_full(self, batch: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """完整前向，返回 logits/value/名次分布等（训练与调试用）。"""
        cfg = self.config
        cls, ent, mask = self._encode_state(batch)

        # ── 候选动作打分 ──
        cand_src = batch["cand_src"].long().clamp(0, cfg.num_entities - 1)
        cand_tgt = batch["cand_tgt"].long().clamp(0, cfg.num_entities - 1)
        src_rep = torch.gather(ent, 1, cand_src.unsqueeze(-1).expand(-1, -1, ent.shape[-1]))
        tgt_rep = torch.gather(ent, 1, cand_tgt.unsqueeze(-1).expand(-1, -1, ent.shape[-1]))
        has_src = batch["cand_num"][..., CAND_FEATURE_OFFSET["has_src"]].unsqueeze(-1)
        has_tgt = batch["cand_num"][..., CAND_FEATURE_OFFSET["has_tgt"]].unsqueeze(-1)
        src_rep = self.src_proj(src_rep) * has_src
        tgt_rep = self.tgt_proj(tgt_rep) * has_tgt
        cand_rep = (
            self.kind_emb(batch["cand_kind"].long().clamp(0, cfg.num_action_kinds - 1))
            + src_rep
            + tgt_rep
            + self.cand_num_mlp(batch["cand_num"])
        )
        cand_rep = self.cand_combine(cand_rep)
        ctx = cls.unsqueeze(1).expand(-1, cand_rep.shape[1], -1)
        logits = self.score_head(torch.cat([cand_rep, ctx], dim=-1)).squeeze(-1)
        logits = self._apply_cand_mask(logits, batch["cand_mask"])

        # ── 价值 ──
        pooled = torch.cat([cls, self._pool_entities(ent, mask)], dim=-1)
        h = self.value_trunk(self.value_combiner(pooled))
        rank_logits = self.rank_head(h)
        if cfg.value_mode == "distribution":
            value, expected_rank = self._value_from_rank_logits(rank_logits)
        else:
            value = torch.tanh(self.scalar_head(h)).squeeze(-1)
            expected_rank = torch.zeros_like(value)
        return {
            "logits": logits,
            "value": value,
            "rank_logits": rank_logits,
            "expected_rank": expected_rank,
            "cls_rep": cls,
            "entity_reps": ent,
            "entity_mask": mask,
        }

    def forward(self, batch: Dict[str, torch.Tensor]) -> Tuple[torch.Tensor, torch.Tensor]:
        """``forward(batch) -> (logits[B,C], value[B])``。"""
        out = self.forward_full(batch)
        return out["logits"], out["value"]

    @staticmethod
    def _apply_cand_mask(logits: torch.Tensor, cand_mask: torch.Tensor) -> torch.Tensor:
        """把无效候选压到 ``MASKED_LOGIT``；整行无有效候选时兜底放开 0 号。"""
        mask = cand_mask.float()
        any_valid = mask.sum(dim=-1, keepdim=True) > 0
        fallback = torch.zeros_like(mask)
        fallback[..., 0] = 1.0
        mask = torch.where(any_valid, mask, fallback)
        return logits.masked_fill(mask < 0.5, MASKED_LOGIT)

    # ── 采样 / 评估 ──
    def act(
        self,
        batch: Dict[str, torch.Tensor],
        greedy: bool = False,
        generator: Optional[torch.Generator] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """``act(batch) -> (actions[B] int64, logp[B], value[B])``。"""
        logits, value = self.forward(batch)
        logp_all = F.log_softmax(logits, dim=-1)
        if greedy:
            actions = logits.argmax(dim=-1)
        else:
            probs = logp_all.exp()
            # 数值兜底：概率和 <=0 时退化为贪心（理论上不会发生）
            bad = ~torch.isfinite(probs.sum(dim=-1)) | (probs.sum(dim=-1) <= 0)
            gen = generator
            if gen is not None and probs.device.type != gen.device.type:
                gen = None  # CUDA 张量不能直接配 CPU generator
            actions = torch.multinomial(probs, num_samples=1, generator=gen).squeeze(-1)
            if bool(bad.any()):
                actions = torch.where(bad, logits.argmax(dim=-1), actions)
        logp = logp_all.gather(1, actions.unsqueeze(-1)).squeeze(-1)
        return actions, logp, value

    def evaluate_actions(
        self,
        batch: Dict[str, torch.Tensor],
        actions: torch.Tensor,
        return_rank_logits: bool = False,
    ) -> Union[
        Tuple[torch.Tensor, torch.Tensor, torch.Tensor],
        Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
    ]:
        """重算给定动作的 ``(logp, entropy, value[, rank_logits])``（PPO 更新用）。"""
        out = self.forward_full(batch)
        logits, value = out["logits"], out["value"]
        logp_all = F.log_softmax(logits, dim=-1)
        actions = actions.long().reshape(-1)
        logp = logp_all.gather(1, actions.unsqueeze(-1)).squeeze(-1)
        # 只在有效候选上计算熵（padding 概率恰为 0）
        probs = logp_all.exp()
        safe_logp = logp_all.clamp_min(math.log(1e-12))
        entropy = -(probs * safe_logp).sum(dim=-1)
        if return_rank_logits:
            return logp, entropy, value, out["rank_logits"]
        return logp, entropy, value

    # ── 工具 ──
    def count_parameters(self) -> int:
        return int(sum(p.numel() for p in self.parameters() if p.requires_grad))

    def resize_card_embedding(
        self,
        new_vocab_size: Optional[int] = None,
        new_vocab: Optional[CardVocab] = None,
    ) -> None:
        """扩充卡牌 embedding（保留旧权重；动态收集新卡后继续训练用）。

        传入 ``new_vocab`` 时同时更新词表与 ``config.vocab_size``；只传
        ``new_vocab_size`` 时需调用方自行保证词表下标一致。
        """
        if isinstance(new_vocab_size, CardVocab):
            new_vocab = new_vocab_size
            new_vocab_size = None
        if new_vocab is not None:
            new_vocab_size = len(new_vocab)
        new_vocab_size = int(new_vocab_size or self.config.vocab_size)
        old = self.card_emb
        if new_vocab_size <= old.num_embeddings:
            if new_vocab is not None:
                self.vocab = new_vocab
            return
        new = nn.Embedding(new_vocab_size, old.embedding_dim, padding_idx=PAD_CARD_INDEX)
        with torch.no_grad():
            new.weight[: old.num_embeddings].copy_(old.weight)
            nn.init.normal_(new.weight[old.num_embeddings:], std=0.02)
        self.card_emb = new
        self.config.vocab_size = new_vocab_size
        if new_vocab is not None:
            self.vocab = new_vocab

    def make_encoder(self) -> ObservationEncoder:
        """用 checkpoint 自带的词表重建一个 ``ObservationEncoder``。"""
        vocab = self.vocab if self.vocab is not None else CardVocab()
        enc = ObservationEncoder(vocab)
        enc.dims = self.encoder_dims
        return enc

    # ── checkpoint ──
    def save(self, path: Union[str, Path], meta: Optional[Dict[str, Any]] = None) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "hsbg.policy.EntityTransformerPolicy",
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "policy_config": self.config.to_dict(),
            "encoder_dims": self.encoder_dims.as_dict(),
            "vocab": self.vocab.to_dict() if self.vocab is not None else None,
            "state_dict": self.state_dict(),
            "meta": dict(meta or {}),
        }
        torch.save(payload, path)
        self.checkpoint_path = str(path)
        return path

    @classmethod
    def load(
        cls,
        path: Union[str, Path],
        map_location: Union[str, torch.device] = "cpu",
    ) -> "EntityTransformerPolicy":
        path = Path(path)
        payload = torch.load(path, map_location=map_location, weights_only=False)
        if not isinstance(payload, dict) or "policy_config" not in payload:
            raise ValueError(f"{path} 不是有效的策略 checkpoint")
        cfg = PolicyConfig.from_dict(payload["policy_config"])
        policy = cls(cfg)
        policy.load_state_dict(payload["state_dict"])
        if payload.get("vocab"):
            policy.vocab = CardVocab.from_dict(payload["vocab"])
        if payload.get("encoder_dims"):
            policy.encoder_dims = EncoderDims.from_dict(payload["encoder_dims"])
        policy.meta = dict(payload.get("meta") or {})
        policy.checkpoint_path = str(path)
        policy.eval()
        return policy

    def extra_repr(self) -> str:  # pragma: no cover - 调试
        return (
            f"dim={self.config.dim}, layers={self.config.layers}, "
            f"heads={self.config.heads}, params={self.count_parameters()}"
        )


# ══════════════════════════════════════════════════════════════════════
# 便捷入口
# ══════════════════════════════════════════════════════════════════════


def build_policy(
    encoder: ObservationEncoder,
    *,
    config: Optional[PolicyConfig] = None,
    **overrides: Any,
) -> EntityTransformerPolicy:
    """按编码器尺寸新建策略（自动补 ``vocab_size`` 等编码相关字段）。"""
    if config is None:
        config = PolicyConfig.for_encoder(encoder, **overrides)
    policy = EntityTransformerPolicy(config)
    policy.vocab = encoder.vocab
    policy.encoder_dims = encoder.dims
    return policy


def load_policy_and_encoder(
    path: Union[str, Path],
    map_location: Union[str, torch.device] = "cpu",
) -> Tuple[EntityTransformerPolicy, ObservationEncoder]:
    """加载 checkpoint 并重建配套编码器（评测/续训入口）。"""
    policy = EntityTransformerPolicy.load(path, map_location=map_location)
    return policy, policy.make_encoder()


__all__ = [
    "PolicyConfig",
    "EntityTransformerPolicy",
    "build_policy",
    "load_policy_and_encoder",
    "CHECKPOINT_FORMAT_VERSION",
    "MASKED_LOGIT",
]
