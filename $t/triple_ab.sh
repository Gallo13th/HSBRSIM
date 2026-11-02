#!/bin/bash
# 第二步：三连供给 A/B（0 / +1.0 / +2.0 / +2.0+freeze）
# 每臂：150 局 8 bot（采集器：goldens/三连/S15/win/rank）+ 96 局 5 席 p0.9（S15）
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.:scripts
CK=runs/az_entity_s25/model.pt
OUT=runs/az_entity_s25/collector
mkdir -p "$OUT"

# tag:triple_bias:pair_freeze
for spec in "t00:0.0:0" "t10:1.0:0" "t20:2.0:0" "t2f:2.0:1"; do
  IFS=: read -r TAG TB PF <<< "$spec"
  echo "=== arm tag=$TAG triple_bias=$TB pair_freeze=$PF collector $(date +%H:%M:%S)"
  "$PY" scripts/chain_collector.py --checkpoint "$CK" --games 150 --device cuda:6 \
    --out-dir "$OUT" --triple-bias "$TB" --pair-freeze "$PF" --tag "$TAG" \
    > "$OUT/collect_$TAG.log" 2>&1
  echo "collector exit=$? $(date +%H:%M:%S)"

  echo "=== arm tag=$TAG quality 5x p0.9 $(date +%H:%M:%S)"
  "$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:6 \
    --games 96 --seed-base 520000 --triple-bias "$TB" --pair-freeze "$PF" \
    --human-boards data/real_library/library_real_quasi_full.jsonl \
    --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
    --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
    --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
    --out "$OUT/q5p09_$TAG.json" > "$OUT/q5p09_$TAG.log" 2>&1
  echo "quality exit=$? $(date +%H:%M:%S)"
done
echo "TRIPLE_AB_DONE"
