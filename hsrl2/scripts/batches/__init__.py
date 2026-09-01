"""批次模块自动发现——批量迁移的零冲突基础设施。

每个批次文件命名 batch_<name>.py，顶层定义脚本类与
``def register() -> list[str]``（内部调用 registry.register 并返回
注册的 card_id 列表）。本包 import 时自动发现并执行全部批次注册。
subagent 只新增自己的 batch_*.py 文件，不再共写 registry.py。
"""

from __future__ import annotations

import importlib
import pkgutil


def _discover() -> None:
    for mod_info in pkgutil.iter_modules(__path__):
        if not mod_info.name.startswith("batch_"):
            continue
        mod = importlib.import_module(f"{__name__}.{mod_info.name}")
        if hasattr(mod, "register"):
            mod.register()


_discover()
