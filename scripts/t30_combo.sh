#!/bin/bash
# t30锛堜笁杩?3.0锛? combo锛圖iscover 3.0 + Triple 3.0锛屾渶缁堝€欓€夐厤鏂癸級
# 姣忚噦锛?50 灞€ 8 bot锛堝惈 final_board 鏄庣粏 鈫?t5+ 韬潗鍗犳瘮锛? 96 灞€ 5 甯?p0.9
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.:scripts
CK=runs/az_entity_s25/model.pt
OUT=runs/az_entity_s25/collector
mkdir -p "$OUT"

run_arm () {
  local TAG="$1"; local DB="$2"; local TB="$3"
  echo "=== arm $TAG discover=$DB triple=$TB collector $(date +%H:%M:%S)"
  "$PY" scripts/chain_collector.py --checkpoint "$CK" --games 150 --device cuda:6 \
    --out-dir "$OUT" --discover-bias "$DB" --discover-targets all \
    --triple-bias "$TB" --pair-freeze 0 --tag "$TAG" > "$OUT/collect_$TAG.log" 2>&1
  echo "collector exit=$? $(date +%H:%M:%S)"
  echo "=== arm $TAG quality 5x p0.9 $(date +%H:%M:%S)"
  "$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:6 \
    --games 96 --seed-base 520000 --discover-bias "$DB" --discover-targets all \
    --triple-bias "$TB" --pair-freeze 0 \
    --human-boards data/real_library/library_real_quasi_full.jsonl \
    --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
    --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
    --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
    --out "$OUT/q5p09_$TAG.json" > "$OUT/q5p09_$TAG.log" 2>&1
  echo "quality exit=$? $(date +%H:%M:%S)"
}

run_arm t30 0.0 3.0
run_arm combo 3.0 3.0
echo BOTH_DONE
