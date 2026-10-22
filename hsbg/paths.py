"""项目路径常量（唯一权威，禁止在别处硬编码相对路径）。"""

from __future__ import annotations

from pathlib import Path

#: 仓库根目录（pyproject.toml 所在目录）
ROOT = Path(__file__).resolve().parent.parent
#: 引擎卡牌数据（hsrl2.db.CardDB.load 读取）
DATA_DIR = ROOT / "data"
#: 原始 CardDefs.xml（数值唯一权威，数据更新时使用）
HSDATA_DIR = ROOT / "hsdata"
#: 运行产物：checkpoint / 训练日志 / 评测结果
RUNS_DIR = ROOT / "runs"
#: 文档
DOCS_DIR = ROOT / "docs"


def ensure_runs_dir(*parts: str) -> Path:
    """创建并返回 ``runs/`` 下的子目录。"""
    p = RUNS_DIR.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
