#!/usr/bin/env python3
"""合并 / 补标沙盒搜索标签：补 ``tier`` / ``carriers``（纯观测解码），并容忍半截 gzip。

`scripts/gen_sandbox_search_labels.py` 新版本在每步记录里直接写 ``tier`` / ``carriers``；
本脚本用于**合并分片**与**补标**早期文件，不改变 obs / π / 动作序列。

用法::

  PYTHONPATH=rust/python:. python scripts/annotate_search_labels.py \
      --in data/search_labels/shards/shard0.jsonl.gz ... \
      --out data/search_labels/sandbox_labels.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from typing import Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.gen_sandbox_search_labels import (build_card_id_map,  # noqa: E402
                                               decode_obs, obs_meta)
from hsbg.az.train.economy_sandbox import carrier_ids  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="合并/补标搜索标签（tier/carriers）")
    ap.add_argument("--in", dest="srcs", nargs="+",
                    default=["data/search_labels/sandbox_labels.jsonl.gz"])
    ap.add_argument("--out", default="data/search_labels/sandbox_labels.annotated.jsonl.gz")
    args = ap.parse_args(argv)
    cards = build_card_id_map()
    cset = set(carrier_ids())
    print(f"[annotate] cid2id={len(cards)} carriers={len(cset)} srcs={len(args.srcs)}",
          flush=True)
    n = steps = 0
    t0 = time.time()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8", compresslevel=6) as fout:
        for src in args.srcs:
            bad = 0
            fin = gzip.open(src, "rt", encoding="utf-8")
            while True:
                try:
                    line = fin.readline()
                except EOFError:      # 半截 gzip（生成被中断）：保留已读部分
                    break
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:   # 截断的最后一行
                    bad += 1
                    break
                if rec.get("type") == "step":
                    f, c, _m = decode_obs(rec["obs"])
                    tier, ncar = obs_meta(f, c, cards, cset)
                    rec["tier"] = int(tier)
                    rec["carriers"] = int(ncar)
                    steps += 1
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            fin.close()
            print(f"[annotate] {src}: done (bad={bad})", flush=True)
    print(f"[annotate] -> {args.out}: lines={n} steps={steps} ({time.time() - t0:.1f}s)",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
