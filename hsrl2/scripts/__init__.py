"""hsrl2 卡牌脚本包。

脚本类由 docs/agents/EFFECT_SCRIPT_SOP.md 流程批量添加，
通过 REGISTRY 绑定 card_id。引擎在运行时由 registry.resolve 绑定。
batches/ 子包自动发现并注册各批次（零冲突并行迁移）。
"""

from hsrl2.scripts.registry import REGISTRY, bind_all
from hsrl2.scripts import batches  # noqa: F401  触发批次自动发现

__all__ = ["REGISTRY", "bind_all"]
