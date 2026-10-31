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
from typing import Any, Dict, List, Optional, Tuple

#: 入日志前从 collect meta 里剔除的字段（体积大且训练中不使用）
SLIM_DROP_KEYS = ("worker_meta", "games_meta")

#: 注入计数/开关（mirror 快照 + 人类战团）：必须进 history 才能验证「是否真的生效」。
#: worker meta 里可能存在（顶层或嵌套 ``collect``），slim 时统一提升到 collect 段顶层。
INJECTION_KEYS = (
    "mirror_on", "mirror_attempt", "mirror_applied", "mirror_rejected",
    "mirror_missing", "mirror_fallback", "mirror_errors",
    "mirror_p", "mirror_sample", "mirror_p_ramp",
    "mirror_seats", "mirror_frames", "mirror_last_rejected",
    "human_board_on", "human_board_attempt", "human_board_applied",
    "human_board_rejected", "human_board_missing", "human_board_errors",
    "human_board_skipped_by_mirror", "human_board_p", "human_board_sample",
    "human_board_seats", "human_board_source", "human_board_last_rejected",
    # 保真度（board/hand/full）与逐字段可得性：验证「是否真的注入了 hand/counters」。
    "human_board_fidelity", "human_board_hand_applied",
    "human_board_counters_applied", "human_board_full_applied",
    "human_board_payload_missing", "human_board_hand_unavailable",
    "human_board_counters_unavailable", "human_board_unavailable_fields",
    "human_board_payload_rows",
)
#: 跨 worker 聚合口径：事件计数求和、开关取 any、概率取均值、设置取首个值。
INJECTION_SUM_KEYS = frozenset({
    "mirror_attempt", "mirror_applied", "mirror_rejected", "mirror_missing",
    "mirror_fallback", "mirror_errors",
    "human_board_attempt", "human_board_applied", "human_board_rejected",
    "human_board_missing", "human_board_errors",
    "human_board_skipped_by_mirror",
    "human_board_hand_applied", "human_board_counters_applied",
    "human_board_full_applied", "human_board_payload_missing",
    "human_board_hand_unavailable", "human_board_counters_unavailable",
})
#: 逐字段可得性计数：跨 worker 逐键求和（dict 合并）。
INJECTION_DICT_KEYS = frozenset({"human_board_unavailable_fields"})
INJECTION_ANY_KEYS = frozenset({"mirror_on", "human_board_on"})
INJECTION_MEAN_KEYS = frozenset({"mirror_p", "human_board_p"})
INJECTION_FIRST_KEYS = frozenset({
    "mirror_sample", "mirror_p_ramp", "mirror_seats", "mirror_frames",
    "human_board_sample", "human_board_seats", "human_board_source",
    "human_board_fidelity", "human_board_payload_rows",
})


def _numeric(value: Any) -> Optional[float]:
    """可当数值聚合的值（bool / numpy 标量也接受；其他类型返回 None）。"""
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def aggregate_injection(sources: Any) -> Dict[str, Any]:
    """把多个 worker meta 聚合为注入计数（缺失键不出现，绝不报错）。

    兼容每个 source 是 dict、或 dict 里再嵌 ``collect``；忽略非 dict。聚合口径：
    计数 sum；``*_on`` any；``*_p`` mean；sample/ramp/source 等取首个非空值。
    """
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, (list, tuple)):
        return {}
    flat: List[Dict[str, Any]] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        flat.append(src)
        inner = src.get("collect")
        if isinstance(inner, dict):
            flat.append(inner)
    out: Dict[str, Any] = {}
    for key in INJECTION_KEYS:
        vals = [s[key] for s in flat if key in s and s[key] is not None]
        if not vals:
            continue
        if key in INJECTION_SUM_KEYS:
            nums = [n for n in (_numeric(v) for v in vals) if n is not None]
            if nums:
                out[key] = int(sum(nums))
        elif key in INJECTION_ANY_KEYS:
            out[key] = bool(any(bool(v) for v in vals))
        elif key in INJECTION_MEAN_KEYS:
            nums = [n for n in (_numeric(v) for v in vals) if n is not None]
            if nums:
                out[key] = float(sum(nums) / len(nums))
        elif key in INJECTION_DICT_KEYS:
            merged: Dict[str, Any] = {}
            for v in vals:
                if not isinstance(v, dict):
                    continue
                for kk, vv in v.items():
                    n = _numeric(vv)
                    if n is not None:
                        merged[str(kk)] = int(merged.get(str(kk), 0) + int(n))
            if merged:
                out[key] = dict(sorted(merged.items()))
        elif key in INJECTION_FIRST_KEYS:
            out[key] = vals[0]
        else:  # 未知的注入键：保留首值，宁可多记也不丢
            out[key] = vals[0]
    return out


def _lift_injection(out: Dict[str, Any],
                    workers: Any = None) -> None:
    """把注入键提升到 collect 段顶层：顶层 → 嵌套 collect → worker_meta 聚合。

    ``workers`` 是**剔除前**的原始 ``worker_meta``（``slim_collect`` 会先复制再删键，
    因此必须由调用方保留引用传入）。
    """
    have = {k for k in INJECTION_KEYS if k in out}
    inner = out.get("collect")
    if isinstance(inner, dict):
        for k in INJECTION_KEYS:
            if k not in have and k in inner:
                out[k] = inner[k]
                have.add(k)
        if workers is None:
            workers = inner.get("worker_meta")
    if workers is None:
        workers = out.get("worker_meta")
    if isinstance(workers, list) and len(have) < len(INJECTION_KEYS):
        agg = aggregate_injection(workers)
        for k, v in agg.items():
            if k not in have:
                out[k] = v
                have.add(k)


def slim_collect(meta: Any) -> Dict[str, Any]:
    """返回去掉大字段后的 collect meta（浅拷贝，不改原对象）。

    同时**保留注入计数**（``mirror_*`` / ``human_board_*``）：这些字段可能出现在
    meta 顶层、嵌套 ``collect`` 或（将被剔除的）``worker_meta`` 里，统一提升到返回
    值的顶层；缺失时不补键、不报错。
    """
    if not isinstance(meta, dict):
        return {}
    out = dict(meta)
    workers = out.get("worker_meta")
    inner = out.get("collect")
    if isinstance(inner, dict) and workers is None:
        workers = inner.get("worker_meta")
    for key in SLIM_DROP_KEYS:
        out.pop(key, None)
    if isinstance(inner, dict):
        inner = dict(inner)
        for key in SLIM_DROP_KEYS:
            inner.pop(key, None)
        out["collect"] = inner
    _lift_injection(out, workers)
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
           "slim_collect", "aggregate_injection", "SLIM_DROP_KEYS",
           "INJECTION_KEYS"]
