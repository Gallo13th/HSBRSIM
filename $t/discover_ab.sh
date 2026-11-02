#!/bin/bash
# Discover 选牌先验 A/B（Lead 新轮次第一步）：0 / +1.0 / +2.0
# 每臂：150 局 8 bot（采集器：选中率/goldens/t15 Σ/win）+ 96 局 5 席 p0.9（S15）
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.:scripts
CK=runs/az_entity_s25/model.pt
OUT=runs/az_entity_s25/collector
mkdir -p "$OUT"

for spec in "b00:0.0" "b10:1.0" "b20:2.0"; do
  TAG=${spec%%:*}
  W=${spec#*:}
  echo "=== arm tag=$TAG bias=$W  collector(150 games, 8bot) $(date +%H:%M:%S)"
  "$PY" scripts/chain_collector.py --checkpoint "$CK" --games 150 --device cuda:6 \
    --out-dir "$OUT" --discover-bias "$W" --discover-targets all --tag "$TAG" \
    > "$OUT/collect_$TAG.log" 2>&1
  echo "collector exit=$? $(date +%H:%M:%S)"

  echo "=== arm tag=$TAG bias=$W  quality(96 games, 5x p0.9) $(date +%H:%M:%S)"
  "$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:6 \
    --games 96 --seed-base 520000 --discover-bias "$W" --discover-targets all \
    --human-boards data/real_library/library_real_quasi_full.jsonl \
    --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
    --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
    --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
    --out "$OUT/q5p09_$TAG.json" > "$OUT/q5p09_$TAG.log" 2>&1
  echo "quality exit=$? $(date +%H:%M:%S)"
done
echo "DISCOVER_AB_DONE"
