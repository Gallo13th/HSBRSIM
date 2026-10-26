"""路径与版本常量（只读参照仓库 + 本仓库）。"""

from __future__ import annotations

import os
from pathlib import Path

#: HSBRSIM 仓库根目录（本文件位于 <root>/tools/ac_conformance/）。
ROOT = Path(__file__).resolve().parent.parent.parent

#: AutoTavern 参照仓库（只读；可用环境变量覆盖）。
AUTOTAVERN_ROOT = Path(
    os.environ.get("AUTOTAVERN_ROOT", str(ROOT.parent / "repos" / "AutoTavern"))
).resolve()

AUTOTAVERN_CARDS = AUTOTAVERN_ROOT / "crates" / "taverngym" / "data" / "cards.json"
AUTOTAVERN_ARCH = AUTOTAVERN_ROOT / "docs" / "ARCHITECTURE.md"
AUTOTAVERN_COMBAT_RS = AUTOTAVERN_ROOT / "crates" / "taverngym" / "src" / "combat.rs"
AUTOTAVERN_CONFIG_RS = AUTOTAVERN_ROOT / "crates" / "taverngym" / "src" / "config.rs"

HSRL2_DATA = ROOT / "data"
HSRL2_CARDS = HSRL2_DATA / "bg_cards.json"
HSRL2_POOL_MINIONS = HSRL2_DATA / "bg_pool_minions.json"

RUNS_DIR = ROOT / "runs" / "conformance"

#: 参照版本 / 被审版本（运行时还会实测，见 run.py 的 meta）。
AUTOTAVERN_VERSION = "36.6.3.253932"
HSRL2_VERSION = "37.0.0.255130"

#: 判定用的种子规模（分布类场景）。
DEFAULT_SEEDS = 48
