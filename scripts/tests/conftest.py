"""测试前置：只保证仓库根在 ``sys.path``。

AutoTavern 引擎（``hsbg_engine``）未构建时，依赖它的测试自行 ``importorskip``。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
