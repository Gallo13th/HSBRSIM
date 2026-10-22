"""训练日志：CSV 逐行记录 + JSON 汇总（写入 ``runs/`` 便于对比复现）。

不引入第三方依赖；CSV 用标准库 ``csv``，JSON 用标准库 ``json``。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class CSVLogger:
    """按固定表头追加写 CSV；缺失字段留空，多余字段忽略。

    第一次 ``log`` 时若未提供 ``fieldnames``，则用该行 key 初始化表头。
    """

    def __init__(self, path: Path, fieldnames: Optional[Iterable[str]] = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fieldnames: Optional[List[str]] = list(fieldnames) if fieldnames else None
        self._fh = None
        self._writer: Optional[csv.DictWriter] = None

    def log(self, row: Dict[str, Any]) -> None:
        if self._writer is None:
            if self.fieldnames is None:
                self.fieldnames = list(row.keys())
            self._fh = open(self.path, "w", encoding="utf-8", newline="")
            self._writer = csv.DictWriter(
                self._fh, fieldnames=self.fieldnames, extrasaction="ignore"
            )
            self._writer.writeheader()
        assert self._writer is not None and self._fh is not None
        clean = {k: _csv_value(v) for k, v in row.items() if k in self._writer.fieldnames}
        self._writer.writerow(clean)
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self._writer = None

    def __enter__(self) -> "CSVLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _csv_value(value: Any) -> Any:
    """把 float 收敛到 6 位小数，便于人工对比；其他原样。"""
    if isinstance(value, float):
        return f"{value:.6g}"
    return value


def write_json(path: Path, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=_json_default)
    return path


def read_json(path: Path) -> Any:
    with open(Path(path), "r", encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(path: Path, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=_json_default) + "\n")
    return path


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):  # numpy 标量
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def format_metrics_table(rows: List[Dict[str, Any]], columns: Optional[List[str]] = None) -> str:
    """把若干行指标渲染成等宽文本表（脚本/日志展示用）。"""
    if not rows:
        return "(无数据)"
    columns = columns or list(rows[0].keys())
    table = [[str(r.get(c, "")) for c in columns] for r in rows]
    widths = [
        max(len(columns[i]), max((len(row[i]) for row in table), default=0))
        for i in range(len(columns))
    ]
    sep = "  ".join("-" * w for w in widths)
    lines = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(columns)), sep]
    for row in table:
        lines.append("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))
    return "\n".join(lines)


__all__ = ["CSVLogger", "write_json", "read_json", "append_jsonl", "format_metrics_table"]
