#!/usr/bin/env python3
"""把多个 ``compound_bc`` npz **按局混采**成一个新数据集（重编号 / 重算 val / 来源标记）。

用途：把正式 S3 教师（170 局、amp 9.14、形状好）与 roll8 动作效率教师（94 局、amp 13.39、
Σ 高）按指定比例混采，给学生一份既保留形状、又保留「预算花满」动作分布的 teacher 数据。

做法
----
- 每个输入按 ``path:weight`` 给相对权重；**按局**（episode）确定性抽样：
  ``T = min_i floor(n_i × Σw / w_i)``，``k_i = floor(T × w_i / Σw)``，抽样用 seed 排序后的
  等距索引（确定性，不依赖 RNG；``--shuffle-seed`` 只打乱**输出局序**）。
- 输出：``episode_id`` 全局重编号、``ep_decisions`` 与逐决策计数一致、``ep_split`` 按输出
  局序每 10 局取 1 局（确定性 10% val）、新增 ``ep_source``（0/1/… = 第几个输入）。
- 复用 ``gen_compound_bc.validate_arrays`` 做合法性自检（动作必须在 mask 上）。

用法::

    python scripts/mix_compound_bc.py \
        --part data/scaling/compound_bc/s3_growth_buff3.npz:2 \
        --part data/scaling/compound_bc/s3_growth_buff3_eff_roll8.npz:1 \
        --out data/scaling/compound_bc/s3_mix_roll8.npz
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "scripts"))

from gen_compound_bc import (  # noqa: E402
    DEC_FIELDS, EP_FIELDS, ACTION_KINDS, field_doc, validate_arrays)

#: 输出里额外加的每局字段（来源下标）
MIX_EP_EXTRA: Tuple[str, ...] = ("ep_source",)


def _pct(v: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(v, dtype=np.float64), q)) if len(v) else 0.0


def _even_indices(n: int, k: int) -> np.ndarray:
    """从 ``n`` 个里确定性等距取 ``k`` 个（k<=n），必要时补齐剩余下标。"""
    if k >= n:
        return np.arange(n)
    idx = np.unique(np.linspace(0, n - 1, k).round().astype(np.int64))
    if idx.size < k:                      # linspace 取整重复时补齐
        rest = np.setdiff1d(np.arange(n), idx)
        idx = np.sort(np.concatenate([idx, rest[: k - idx.size]]))
    return idx[:k]


def _parse_parts(specs: Sequence[str]) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for s in specs:
        s = s.strip()
        if not s:
            continue
        path, _, w = s.rpartition(":")
        if path and w:
            out.append((path, float(w)))
        else:
            out.append((s, 1.0))
    if len(out) < 1:
        raise SystemExit("至少给一个 --part path[:weight]")
    return out


def mix(parts: Sequence[Tuple[str, float]], out_path: str, shuffle_seed: int = 0,
        source_names: Sequence[str] = ()) -> Dict[str, Any]:
    t0 = time.time()
    datas: List[Dict[str, np.ndarray]] = []
    for path, _w in parts:
        d = np.load(path)
        datas.append({k: d[k] for k in d.files})
        d.close()
    weights = np.asarray([w for _p, w in parts], dtype=np.float64)
    weights = weights / weights.sum()
    n_eps = [int(d["ep_seed"].shape[0]) for d in datas]
    # 最大可行总局数：每个输入都不能超过自己的局数
    total = int(min(int(n * (1.0 / w)) for n, w in zip(n_eps, weights)))
    take = [max(1, min(int(n), int(np.floor(total * w)))) for n, w in zip(n_eps, weights)]

    pieces: List[Dict[str, np.ndarray]] = []
    source_meta: List[Dict[str, Any]] = []
    new_eid = 0
    for si, (d, (path, _w), k) in enumerate(zip(datas, parts, take)):
        eid = d["episode_id"].astype(np.int64)
        order = np.argsort(d["ep_seed"], kind="stable")
        sel = order[_even_indices(len(order), k)]
        rows: List[np.ndarray] = []
        ep_rows: List[int] = []
        for local in sel:
            r = np.flatnonzero(eid == int(local))
            rows.append(r)
            ep_rows.append(int(local))
        rows_arr = np.concatenate(rows) if rows else np.zeros(0, dtype=np.int64)
        piece: Dict[str, np.ndarray] = {}
        for f in DEC_FIELDS:
            arr = np.asarray(d[f])[rows_arr]
            if f == "episode_id":
                # 本输入内 local episode → 输出全局 id（按 ep_rows 顺序）
                remap = np.zeros(len(d["ep_seed"]), dtype=np.int32)
                for out_i, local in enumerate(ep_rows):
                    remap[local] = new_eid + out_i
                arr = remap[eid[rows_arr]]
            piece[f] = arr
        for f in EP_FIELDS:
            piece[f] = np.asarray(d[f])[np.asarray(ep_rows, dtype=np.int64)]
        piece["ep_source"] = np.full(len(ep_rows), si, dtype=np.uint8)
        # 在输入内部按 seed 排序输出（跨输入由 --shuffle-seed 打乱）
        for f in EP_FIELDS + MIX_EP_EXTRA:
            piece[f] = piece[f]
        pieces.append(piece)
        source_meta.append({
            "index": si,
            "path": os.path.abspath(path),
            "name": str(source_names[si]) if si < len(source_names) else f"part{si}",
            "weight": float(_w),
            "episodes_available": int(n_eps[si]),
            "episodes_taken": int(len(ep_rows)),
            "decisions_taken": int(len(rows_arr)),
            "amp_total_mean": float(np.mean(piece["ep_amp_total"])) if len(ep_rows) else 0.0,
            "sigma_t15_p50": _pct([float(x) for x in piece["ep_sigma_t15"]], 50),
            "r12_15_p50": _pct([float(x) for x in piece["ep_r12_15"]], 50),
        })
        new_eid += len(ep_rows)
        datas[si] = {}  # 尽早释放

    # 跨输入打乱「局」的顺序（局内决策保持连续）
    ep_piece_list = []
    for si, piece in enumerate(pieces):
        ep_piece_list.extend([si] * len(piece["ep_seed"]))
    rng = np.random.default_rng(int(shuffle_seed))
    perm = rng.permutation(len(ep_piece_list))
    # 每输入的决策行按局连续：用 ep_decisions 切块（块内保持原顺序）
    blocks: List[Dict[str, np.ndarray]] = []
    for si, piece in enumerate(pieces):
        n_ep = int(piece["ep_seed"].shape[0])
        pos = 0                     # 每个输入的各局独立切块（片内下标从 0 开始）
        for e in range(n_ep):
            n = int(piece["ep_decisions"][e])
            block = {f: piece[f][pos:pos + n] for f in DEC_FIELDS}
            block["_ep"] = {f: piece[f][e:e + 1] for f in EP_FIELDS + MIX_EP_EXTRA}
            blocks.append(block)
            pos += n
        if pos != int(piece["action"].shape[0]):
            raise RuntimeError(f"第 {si} 个输入切块行数不一致：{pos} != "
                               f"{int(piece['action'].shape[0])}")
    # 输出局序：按 perm 打乱局序、局内行连续；episode_id 全局重编号
    blocks_out: List[Dict[str, np.ndarray]] = []
    out_eid = 0
    for j in perm:
        b = blocks[int(j)]
        if int(b["_ep"]["ep_decisions"][0]) != len(b["action"]):
            raise RuntimeError("ep_decisions 与 block 行数不一致")
        b = {f: b[f].copy() for f in DEC_FIELDS}
        b["episode_id"] = np.full(len(b["action"]), out_eid, dtype=np.int32)
        b["_ep"] = blocks[int(j)]["_ep"]
        blocks_out.append(b)
        out_eid += 1
    # 拼接
    out = {f: np.concatenate([b[f] for b in blocks_out], axis=0) for f in DEC_FIELDS}
    for f in EP_FIELDS + MIX_EP_EXTRA:
        out[f] = np.concatenate([b["_ep"][f] for b in blocks_out], axis=0)
    out["ep_split"] = (np.arange(len(blocks_out)) % 10 == 0).astype(np.uint8)
    validation = validate_arrays(out, "mix")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    np.savez(out_path, **out)
    ep_s15 = out["ep_sigma_t15"].astype(np.float64)
    by_source = {}
    for si, meta in enumerate(source_meta):
        m = out["ep_source"] == si
        by_source[meta["name"]] = {
            **{k: meta[k] for k in ("path", "weight", "episodes_available",
                                    "episodes_taken", "decisions_taken")},
            "mix_episodes": int(m.sum()),
            "mix_amp_total_mean": float(np.mean(out["ep_amp_total"][m])) if m.any() else 0.0,
            "mix_sigma_t15_p50": _pct([float(x) for x in out["ep_sigma_t15"][m]], 50),
        }
    meta_out = {
        "kind": "compound_bc_mix",
        "version": 1,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "out": os.path.abspath(out_path),
        "parts": source_meta,
        "by_source": by_source,
        "episodes": int(len(blocks_out)),
        "decisions": int(out["action"].shape[0]),
        "total_episodes_available": int(sum(n_eps)),
        "take_ratio": [int(t) for t in take],
        "amp_total_mean": float(np.mean(out["ep_amp_total"])),
        "sigma_t15_p50": _pct([float(x) for x in ep_s15], 50),
        "sigma_t15_mean": float(np.mean(ep_s15)),
        "r12_15_p50": _pct([float(x) for x in out["ep_r12_15"]], 50),
        "spells_mean": float(np.mean(out["ep_spells_t15"])),
        "goldens_mean": float(np.mean(out["ep_goldens_t15"])),
        "feature_dtype": str(out["features"].dtype),
        "val_games": int(out["ep_split"].sum()),
        "validation": validation,
        "fields": {**field_doc(),
                   "ep_source": "uint8[E]（0,1,… = --part 的输入下标；用于混采配比追溯）"},
        "seconds": time.time() - t0,
    }
    with open(os.path.splitext(out_path)[0] + "_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_out, f, ensure_ascii=False, indent=1, default=float)
    return meta_out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="compound_bc npz 按局混采")
    ap.add_argument("--part", action="append", default=[],
                    help="path[:weight]，可多次；权重为相对局数配比")
    ap.add_argument("--name", action="append", default=[],
                    help="对应 --part 的名字（可选，写进 meta）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--shuffle-seed", type=int, default=0)
    args = ap.parse_args(argv)
    parts = _parse_parts(args.part)
    meta = mix(parts, args.out, shuffle_seed=int(args.shuffle_seed),
               source_names=list(args.name))
    print(f"[mix] {meta['episodes']} 局 / {meta['decisions']} 决策 / "
          f"{os.path.getsize(args.out) / 1e6:.0f}MB → {args.out}")
    print(f"      amp={meta['amp_total_mean']:.2f}  t15 Σ p50={meta['sigma_t15_p50']:.0f} "
          f"r12 p50={meta['r12_15_p50']:.2f}  val={meta['val_games']} 局")
    for name, m in meta["by_source"].items():
        print(f"      [{name}] 取 {m['episodes_taken']}/{m['episodes_available']} 局 "
              f"→ {m['mix_episodes']} 局 amp={m['mix_amp_total_mean']:.2f} "
              f"Σ p50={m['mix_sigma_t15_p50']:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
