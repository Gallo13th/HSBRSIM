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
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from hsbg.env.spec import NUM_ACTION_KINDS, PLAYER_MAX, Observation
from hsbg.policy.encoder import (
    CAND_FEATURE_OFFSET,
    CAND_NUM_DIM,
    ENCODER_DIMS,
    MAX_ZONE_SLOTS,
    NUM_ENTITIES,
    EncoderDims,
    ObservationEncoder,
    PAD_CARD_INDEX,
    CardVocab,
)

#: checkpoint 格式版本（结构/观测 schema 不兼容时 +1）
#: * 1：观测 v1/v2（12 种动作、cand_num 38 维）
#: * 2：观测 v3（13 种动作含 MOVE_MINION、cand_num 39 维、
#:   ``entity_secondary`` 编码 pending_choice_options.secondary_id）；
#:   见 ``docs/POLICY_OBS_V3.md``
CHECKPOINT_FORMAT_VERSION = 2
#: 构建 checkpoint 时的观测 schema 版本（写进 payload 用于兼容性检查）
OBS_SCHEMA_VERSION = int(Observation.version)
#: 掩码 logit 的下界（有限值，避免 -inf 造成 NaN 梯度）
MASKED_LOGIT = -1e9


class CheckpointCompatibilityError(ValueError):
    """checkpoint 与当前观测/网络 schema 不兼容（需要迁移或重训）。

    典型场景：观测 v2 时代（``Observation.version == 2``）训练出的 ckpt 只有
    12 种动作 kind / 38 维候选特征，而观测 v3 追加了 ``MOVE_MINION``（13 种 /
    39 维）。直接加载会**静默**把 move_minion 当成 choose 且 one-hot 列错位，
    因此这里显式拒绝；迁移入口见 :func:`migrate_legacy_checkpoint` 与
    :meth:`EntityTransformerPolicy.load` 的 ``allow_legacy=True``。
    """



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
            num_action_kinds=self.num_action_kinds,
        )


# ══════════════════════════════════════════════════════════════════════
# checkpoint 兼容性检查 / 旧 ckpt 迁移
# ══════════════════════════════════════════════════════════════════════

#: 不随观测 v2→v3 变化的编码尺寸；迁移时必须与当前一致
_STABLE_ENCODER_DIMS: Dict[str, int] = {
    "num_entities": NUM_ENTITIES,
    "entity_num_dim": ENCODER_DIMS.entity_num_dim,
    "global_dim": ENCODER_DIMS.global_dim,
    "candidate_max": ENCODER_DIMS.candidate_max,
    "num_zones": ENCODER_DIMS.num_zones,
    "num_card_types": ENCODER_DIMS.num_card_types,
}


def checkpoint_incompatibilities(payload: Dict[str, Any]) -> List[str]:
    """返回 ckpt 与当前代码不兼容的原因列表（空列表 = 可直接加载）。"""
    reasons: List[str] = []
    if not isinstance(payload, dict):
        return ["payload 不是 dict"]
    fmt = int(payload.get("format_version", 1) or 1)
    if fmt < CHECKPOINT_FORMAT_VERSION:
        reasons.append(
            f"format_version={fmt}（当前 {CHECKPOINT_FORMAT_VERSION}）"
        )
    obs_version = payload.get("obs_version")
    if obs_version is None:
        reasons.append("缺少 obs_version 字段（观测 v2 时代保存的 ckpt）")
    elif int(obs_version) != OBS_SCHEMA_VERSION:
        reasons.append(
            f"obs_version={obs_version}（当前 {OBS_SCHEMA_VERSION}）"
        )
    cfg = payload.get("policy_config") or {}
    dims = payload.get("encoder_dims") or {}
    cfg_kinds = int(cfg.get("num_action_kinds", NUM_ACTION_KINDS))
    cfg_cand = int(cfg.get("cand_num_dim", CAND_NUM_DIM))
    if cfg_kinds != NUM_ACTION_KINDS:
        reasons.append(
            f"policy_config.num_action_kinds={cfg_kinds}（当前 {NUM_ACTION_KINDS}："
            "观测 v3 新增 MOVE_MINION）"
        )
    if cfg_cand != CAND_NUM_DIM:
        reasons.append(
            f"policy_config.cand_num_dim={cfg_cand}（当前 {CAND_NUM_DIM}："
            "kind one-hot 12→13）"
        )
    dims_kinds = dims.get("num_action_kinds")
    if dims_kinds is not None and int(dims_kinds) != NUM_ACTION_KINDS:
        reasons.append(
            f"encoder_dims.num_action_kinds={dims_kinds}（当前 {NUM_ACTION_KINDS}）"
        )
    dims_cand = dims.get("cand_num_dim")
    if dims_cand is not None and int(dims_cand) != CAND_NUM_DIM:
        reasons.append(
            f"encoder_dims.cand_num_dim={dims_cand}（当前 {CAND_NUM_DIM}）"
        )
    return reasons


def _legacy_error_message(path: Path, reasons: Sequence[str]) -> str:
    bullet = "".join(f"  - {r}\n" for r in reasons)
    return (
        f"{path} 是旧观测（v2）时代的策略 checkpoint，与当前观测 v3 不兼容：\n"
        f"{bullet}"
        "观测 v3 变更（详见 docs/POLICY_OBS_V3.md）：\n"
        "  * ActionKind 追加 MOVE_MINION（12→13 类，既有索引不变）；\n"
        "  * 候选特征 cand_num 由 38 维变为 39 维（kind one-hot 变宽）；\n"
        "  * 旧 ckpt 的 kind_emb 只有 12 行、cand_num_mlp 输入只有 38 维，\n"
        "    直接加载会静默把 move_minion 当成 choose 且特征列错位。\n"
        "处理方式（任选其一）：\n"
        "  1) 推荐：用观测 v3 重新训练/续训（旧策略没有走位能力）；\n"
        "  2) 迁移旧权重（保留除 MOVE_MINION 外全部参数）：\n"
        "       from hsbg.policy.model import migrate_legacy_checkpoint\n"
        "       migrate_legacy_checkpoint('OLD.pt', 'NEW.pt')\n"
        "     或 EntityTransformerPolicy.load(path, allow_legacy=True)\n"
        "     （内存迁移：kind_emb 新增行用旧行均值初始化，cand_num_mlp 新增\n"
        "     kind 列权重置 0；MOVE_MINION 仍需继续训练才可信）。"
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
        # v3：choice 选项的第二 id（Dark Gift 的 gift_id / 任务 offer 的
        # reward_id）复用卡牌 embedding。第二 id 与主 id 的取值域不相交
        # （gift/reward id 不会作为实体主 card_id 出现），因此共享词表/权重
        # 不会与主 id 语义冲突，也不新增参数、不破坏旧 ckpt 的 state_dict。
        # 缺失该 key（旧编码数据）或为 0（无第二 id）时 padding 行为零向量。
        secondary = batch.get("entity_secondary")
        if secondary is not None:
            sec = secondary.long().clamp(0, cfg.vocab_size - 1)
            ent = ent + self.card_emb(sec)
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
            # 观测 schema 版本（加载时校验；旧 ckpt 缺这个 key）
            "obs_version": OBS_SCHEMA_VERSION,
            "num_action_kinds": NUM_ACTION_KINDS,
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
        *,
        allow_legacy: Optional[bool] = None,
    ) -> "EntityTransformerPolicy":
        """加载 checkpoint。

        旧观测（v2）ckpt 的兼容策略（``allow_legacy``）：

        * ``None``（默认）：**自动内存迁移 + UserWarning**（警告含迁移说明与
          命令）。旧产物（如 ``runs/bc/official_320/policy_bc.pt``）仍可直接
          评测/续训，但不会静默——每次加载都会提示"MOVE_MINION 未经训练"；
        * ``False``：严格模式，直接抛 :class:`CheckpointCompatibilityError`
          （CI/新训练入口建议用；避免误用迁移后的旧权重）；
        * ``True``：静默内存迁移（供 :func:`migrate_legacy_checkpoint` 等显式
          迁移流程使用）。

        迁移只对齐"动作种类/候选特征维度"的结构变化（见
        :meth:`_migrate_legacy_payload`）；结构差异更大时无条件拒绝。
        """
        path = Path(path)
        payload = torch.load(path, map_location=map_location, weights_only=False)
        if not isinstance(payload, dict) or "policy_config" not in payload:
            raise ValueError(f"{path} 不是有效的策略 checkpoint")
        raw_obs_version = payload.get("obs_version")
        if raw_obs_version is not None and int(raw_obs_version) > OBS_SCHEMA_VERSION:
            raise CheckpointCompatibilityError(
                f"{path} 的 obs_version={raw_obs_version} 比当前代码支持的 "
                f"{OBS_SCHEMA_VERSION} 更新（无法降级加载，请更新代码）"
            )
        reasons = checkpoint_incompatibilities(payload)
        migrated = bool(reasons)
        if migrated:
            if allow_legacy is False:
                raise CheckpointCompatibilityError(
                    _legacy_error_message(path, reasons)
                )
            if allow_legacy is None:
                warnings.warn(
                    f"{path} 是旧观测（v2）时代的策略 checkpoint，已自动做内存"
                    "迁移后加载（不落盘）：" + "；".join(reasons) + "。"
                    "迁移规则：kind_emb 新增 MOVE_MINION 行=旧行均值、"
                    "cand_num_mlp 新 kind 列权重=0，其余权重保留；"
                    "MOVE_MINION 未经训练，建议继续训练后再用于评测。"
                    "详见 docs/POLICY_OBS_V3.md；严格报错用 "
                    "allow_legacy=False，落盘迁移用 migrate_legacy_checkpoint()。",
                    UserWarning,
                    stacklevel=2,
                )
            payload = cls._migrate_legacy_payload(path, payload)
        cfg = PolicyConfig.from_dict(payload["policy_config"])
        policy = cls(cfg)
        policy.load_state_dict(payload["state_dict"])
        if payload.get("vocab"):
            policy.vocab = CardVocab.from_dict(payload["vocab"])
        if payload.get("encoder_dims"):
            policy.encoder_dims = EncoderDims.from_dict(payload["encoder_dims"])
        policy.meta = dict(payload.get("meta") or {})
        if migrated:
            policy.meta["legacy_migrated"] = True
        policy.checkpoint_path = str(path)
        policy.eval()
        return policy

    @classmethod
    def _migrate_legacy_payload(
        cls,
        path: Path,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """观测 v2 ckpt → v3 结构的内存迁移（不落盘）。

        * ``kind_emb.weight``：``[12, d]`` → ``[13, d]``，新增 MOVE_MINION 行
          用旧 12 行均值初始化（尺度与旧行一致，初始行为接近"平均动作"）；
        * ``cand_num_mlp.0.weight``：``[d, 38]`` → ``[d, 39]``，kind one-hot
          列变宽一位——新 MOVE_MINION 列权重置 0，其后 26 维特征列原样右移；
        * 其余参数原样保留（state_dict 中新增的参数保持随机初始化）。
        """
        cfg_in = dict(payload.get("policy_config") or {})
        dims_in = dict(payload.get("encoder_dims") or {})
        state_in = dict(payload.get("state_dict") or {})
        kind_old = state_in.get("kind_emb.weight")
        cand_w = state_in.get("cand_num_mlp.0.weight")
        if kind_old is None or kind_old.ndim != 2:
            raise CheckpointCompatibilityError(
                f"迁移失败：{path} 缺少 kind_emb.weight，无法自动迁移"
            )
        if cand_w is None or cand_w.ndim != 2:
            raise CheckpointCompatibilityError(
                f"迁移失败：{path} 缺少 cand_num_mlp.0.weight，无法自动迁移"
            )
        old_kinds = int(kind_old.shape[0])
        old_cand = int(cand_w.shape[1])
        tail = CAND_NUM_DIM - NUM_ACTION_KINDS
        if old_cand - old_kinds != tail:
            raise CheckpointCompatibilityError(
                f"迁移失败：{path} 的 cand_num_dim={old_cand} 与 "
                f"num_action_kinds={old_kinds} 不符合 v2 布局（差值应为 {tail}）"
            )
        # 其它编码尺寸必须与当前代码一致，否则不是"仅 v2→v3 升级"
        for key, expected in _STABLE_ENCODER_DIMS.items():
            got = dims_in.get(key, cfg_in.get(key))
            if got is not None and int(got) != int(expected):
                raise CheckpointCompatibilityError(
                    f"迁移失败：{path} 的 {key}={got} 与当前 {expected} 不一致"
                    "（差异不止观测 v2→v3，请重新训练）"
                )
        new_cfg_dict = dict(cfg_in)
        new_cfg_dict["num_action_kinds"] = NUM_ACTION_KINDS
        new_cfg_dict["cand_num_dim"] = CAND_NUM_DIM
        new_cfg = PolicyConfig.from_dict(new_cfg_dict)
        policy = cls(new_cfg)
        new_state = policy.state_dict()
        merged: Dict[str, torch.Tensor] = {}
        for key, target in new_state.items():
            old = state_in.get(key)
            if old is None:
                merged[key] = target  # 新增参数：保持初始化
                continue
            if tuple(old.shape) == tuple(target.shape):
                merged[key] = old
                continue
            if key == "kind_emb.weight":
                fixed = target.clone()
                rows = min(int(old.shape[0]), int(target.shape[0]))
                fixed[:rows] = old[:rows]
                if rows < target.shape[0]:
                    # 新增 kind 用旧行均值初始化（不要 N(0,1) 随机，避免初始偏向）
                    fixed[rows:] = old.mean(dim=0)
                merged[key] = fixed
                continue
            if key == "cand_num_mlp.0.weight":
                fixed = target.clone()
                fixed[:, :old_kinds] = old[:, :old_kinds]
                fixed[:, old_kinds:NUM_ACTION_KINDS] = 0.0
                fixed[:, NUM_ACTION_KINDS:NUM_ACTION_KINDS + tail] = old[:, old_kinds:]
                merged[key] = fixed
                continue
            raise CheckpointCompatibilityError(
                f"迁移失败：{path} 的 {key} 形状 {tuple(old.shape)} 无法自动对齐到 "
                f"{tuple(target.shape)}（结构差异不止观测 v2→v3，请重新训练）"
            )
        policy.load_state_dict(merged)
        meta_out = dict(payload.get("meta") or {})
        meta_out["legacy_migration"] = {
            "source": str(path),
            "from_format_version": int(payload.get("format_version", 1) or 1),
            "from_obs_version": payload.get("obs_version"),
            "from_num_action_kinds": old_kinds,
            "from_cand_num_dim": old_cand,
            "note": (
                "kind_emb 新增行=旧行均值；cand_num_mlp 新 kind 列=0；"
                "MOVE_MINION 未经训练，需继续训练才可信。"
            ),
        }
        return {
            "format": "hsbg.policy.EntityTransformerPolicy",
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "obs_version": OBS_SCHEMA_VERSION,
            "num_action_kinds": NUM_ACTION_KINDS,
            "policy_config": policy.config.to_dict(),
            "encoder_dims": policy.config.encoder_dims().as_dict(),
            "vocab": payload.get("vocab"),
            "state_dict": policy.state_dict(),
            "meta": meta_out,
        }

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


def migrate_legacy_checkpoint(
    path: Union[str, Path],
    out_path: Optional[Union[str, Path]] = None,
    *,
    map_location: Union[str, torch.device] = "cpu",
) -> Path:
    """把观测 v2 时代的旧 ckpt 迁移成当前 checkpoint 格式（落盘）。

    用法::

        from hsbg.policy.model import migrate_legacy_checkpoint
        new_path = migrate_legacy_checkpoint("runs/ppo/official_v3/policy_final.pt")

    默认输出到同目录 ``<name>_obs_v3.pt``；迁移后可直接
    ``load_policy_and_encoder(new_path)``（无需 ``allow_legacy``）。
    迁移只恢复"除 MOVE_MINION 外"的旧权重，策略仍需继续训练。
    """
    path = Path(path)
    legacy = EntityTransformerPolicy.load(
        path, map_location=map_location, allow_legacy=True
    )
    out = (
        Path(out_path)
        if out_path is not None
        else path.with_name(path.stem + "_obs_v3.pt")
    )
    # 保留旧 meta（含 legacy_migration 迁移记录，便于溯源）
    return legacy.save(out, meta=dict(legacy.meta))


def load_policy_and_encoder(
    path: Union[str, Path],
    map_location: Union[str, torch.device] = "cpu",
    *,
    allow_legacy: Optional[bool] = None,
) -> Tuple[EntityTransformerPolicy, ObservationEncoder]:
    """加载 checkpoint 并重建配套编码器（评测/续训入口）。

    旧观测（v2）ckpt 默认"迁移 + 警告"（见 :meth:`EntityTransformerPolicy.load`）；
    ``allow_legacy=False`` 严格报错，``True`` 静默迁移。
    """
    policy = EntityTransformerPolicy.load(
        path, map_location=map_location, allow_legacy=allow_legacy
    )
    return policy, policy.make_encoder()


__all__ = [
    "PolicyConfig",
    "EntityTransformerPolicy",
    "CheckpointCompatibilityError",
    "build_policy",
    "load_policy_and_encoder",
    "migrate_legacy_checkpoint",
    "checkpoint_incompatibilities",
    "CHECKPOINT_FORMAT_VERSION",
    "OBS_SCHEMA_VERSION",
    "MASKED_LOGIT",
]
