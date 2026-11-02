#!/bin/bash
# Discover 先验 +3.0 补充臂（判据需要 ≥70% 选中率，0/+1/+2 的趋势是 0→51.7→61.8）
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.:scripts
OUT=runs/az_entity_s25/collector

"$PY" scripts/chain_collector.py --checkpoint runs/az_entity_s25/model.pt --games 150 \
  --device cuda:6 --out-dir "$OUT" --discover-bias 3.0 --discover-targets all --tag b30 \
  > "$OUT/collect_b30.log" 2>&1
echo "collector exit=$? $(date +%H:%M:%S)"

"$PY" scripts/quality_monitor.py --checkpoint runs/az_entity_s25/model.pt --arch entity \
  --device cuda:6 --games 96 --seed-base 520000 --discover-bias 3.0 --discover-targets all \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
  --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --out "$OUT/q5p09_b30.json" > "$OUT/q5p09_b30.log" 2>&1
echo "quality exit=$? $(date +%H:%M:%S)"
echo B30_DONE
