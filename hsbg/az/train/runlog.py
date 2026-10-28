"""训练 run 日志：`history.jsonl` 追加写（替代每 iteration 全量重写 history.json）。

为什么：stage-1 里 history.json 长到 **97 MB**，每 iteration `json.dumps(indent=2)` 重写
耗时 **3.61 s**（实测），而单条记录 compact 只有 ~43 KB、追加写 ~0 s。本模块提供：

- ``append_record(path, rec)``：追加一行 compact JSON（O(1)，与训练时长无关）；
- ``read_run(path)``：读回 `(header, records)`，兼容旧的 `history.json`
  （``{"history": [...]}`` 结构）；
- ``write_summary(path, summary)``：收尾写一个**聚合** summary（不再内嵌全量 history）。

同时提供 ``slim_collect``：把 collect meta 里**从不使用**的大字段
（``worker_meta`` / ``games_meta``，单条约 40 KB）去掉后再入日志。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

#: 入日志前从 collect meta 里剔除的字段（体积大且训练中不使用）
SLIM_DROP_KEYS = ("worker_meta", "games_meta")


def slim_collect(meta: Any) -> Dict[str, Any]:
    """返回去掉大字段后的 collect meta（浅拷贝，不改原对象）。"""
    if not isinstance(meta, dict):
        return {}
    out = dict(meta)
    for key in SLIM_DROP_KEYS:
        out.pop(key, None)
    inner = out.get("collect")
    if isinstance(inner, dict):
        inner = dict(inner)
        for key in SLIM_DROP_KEYS:
            inner.pop(key, None)
        out["collect"] = inner
    return out


def append_record(path: str, rec: Dict[str, Any]) -> None:
    """追加一条记录（compact JSON + 换行）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_header(path: str, args: Dict[str, Any]) -> None:
    """写入首行 header（args/版本），只在文件不存在时写。"""
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "header", "args": args},
                           ensure_ascii=False, separators=(",", ":")) + "\n")


def read_run(path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """读取 jsonl（或旧 json）→ (header, records)；文件不存在返回 ({}, [])。"""
    if not os.path.isfile(path):
        return {}, []
    header: Dict[str, Any] = {}
    records: List[Dict[str, Any]] = []
    if path.endswith(".jsonl"):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 崩溃时可能留下半行，跳过
                if isinstance(obj, dict) and obj.get("type") == "header":
                    header = dict(obj.get("args") or {})
                    header["_raw"] = obj
                else:
                    records.append(obj)
        return header, records
    # 兼容旧格式
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        return {}, []
    if isinstance(data, dict):
        return dict(data.get("args") or {}), list(data.get("history") or [])
    return {}, []


def write_summary(path: str, summary: Dict[str, Any]) -> str:
    """原子写聚合 summary（不含全量 history）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


__all__ = ["append_record", "read_run", "write_header", "write_summary",
           "slim_collect", "SLIM_DROP_KEYS"]
