"""启动 HSBRSIM Web 控制台：python scripts/webui.py --port 8765."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.webui.server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
