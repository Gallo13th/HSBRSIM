#!/bin/bash
# D3+T2 组合臂（Lead：验证 Triple 2.0 优于 3.0）
# 判据：goldens >=1.7 且 8bot S15 >=950 且 5xp0.9 S15 >=270
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.:scripts
CK=runs/az_entity_s25/model.pt
OUT=runs/az_entity_s25/collector

echo "=== arm d3t2 discover=3.0 triple=2.0 collector $(date +%H:%M:%S)"
"$PY" scripts/chain_collector.py --checkpoint "$CK" --games 150 --device cuda:6 \
  --out-dir "$OUT" --discover-bias 3.0 --discover-targets all \
  --triple-bias 2.0 --pair-freeze 0 --tag d3t2 > "$OUT/collect_d3t2.log" 2>&1
echo "collector exit=$? $(date +%H:%M:%S)"

echo "=== arm d3t2 quality 5x p0.9 $(date +%H:%M:%S)"
"$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:6 \
  --games 96 --seed-base 520000 --discover-bias 3.0 --discover-targets all \
  --triple-bias 2.0 --pair-freeze 0 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
  --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --out "$OUT/q5p09_d3t2.json" > "$OUT/q5p09_d3t2.log" 2>&1
echo "quality exit=$? $(date +%H:%M:%S)"
echo D3T2_DONE
