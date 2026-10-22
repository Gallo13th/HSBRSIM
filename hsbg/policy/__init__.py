"""``hsbg.policy`` — 观测编码 + 实体 Transformer 策略网络。

* :mod:`hsbg.policy.encoder`  —— ``CardVocab`` / ``ObservationEncoder``（纯 numpy）
* :mod:`hsbg.policy.synthetic` —— 合成观测工厂（Mock 环境 / 测试用）
* :mod:`hsbg.policy.model`    —— ``EntityTransformerPolicy``（torch，懒加载）

``model`` 需要 torch；为保证"只做数据检查/编码"的场景不必导入 torch，这里对
模型符号使用惰性导出（``from hsbg.policy import EntityTransformerPolicy``）。
"""

from __future__ import annotations

from typing import Any

from hsbg.policy.encoder import (
    CardVocab,
    EncoderDims,
    ENCODER_DIMS,
    ENCODED_KEYS,
    GLOBAL_DIM,
    ENTITY_NUM_DIM,
    CAND_NUM_DIM,
    NUM_ENTITIES,
    ObservationEncoder,
    collect_card_ids,
    entity_index,
    stack_encoded,
    to_torch,
)

#: 惰性导出的模型符号（避免在纯编码场景导入 torch）
_LAZY_MODEL_EXPORTS = {
    "PolicyConfig",
    "EntityTransformerPolicy",
    "build_policy",
    "load_policy_and_encoder",
    "MASKED_LOGIT",
    "CHECKPOINT_FORMAT_VERSION",
}

__all__ = [
    "CardVocab",
    "ObservationEncoder",
    "EncoderDims",
    "ENCODER_DIMS",
    "ENCODED_KEYS",
    "NUM_ENTITIES",
    "ENTITY_NUM_DIM",
    "GLOBAL_DIM",
    "CAND_NUM_DIM",
    "collect_card_ids",
    "entity_index",
    "stack_encoded",
    "to_torch",
    "PolicyConfig",
    "EntityTransformerPolicy",
    "build_policy",
    "load_policy_and_encoder",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODEL_EXPORTS:
        from hsbg.policy import model

        return getattr(model, name)
    raise AttributeError(f"module 'hsbg.policy' has no attribute {name!r}")
