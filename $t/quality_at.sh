#!/bin/bash
# 用法: quality_at.sh <ckpt> <tag>   在 cuda:6 上跑 96 局质量面板（与训练对手同分布：5 席 p0.9 full）
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
CKPT="$1"; TAG="$2"
OUT=runs/az_entity_s22/eval
mkdir -p "$OUT"
"$PY" scripts/quality_monitor.py --checkpoint "$CKPT" --arch entity \
  --device cuda:6 --games 96 --seed-base 520000 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
  --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --out "$OUT/quality_${TAG}.json" > "$OUT/quality_${TAG}.log" 2>&1
echo "quality exit=$? tag=$TAG"
