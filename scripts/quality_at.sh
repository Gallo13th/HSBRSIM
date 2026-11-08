#!/bin/bash
# 鐢ㄦ硶: quality_at.sh <ckpt> <tag>   鍦?cuda:6 涓婅窇 96 灞€璐ㄩ噺闈㈡澘锛堜笌璁粌瀵规墜鍚屽垎甯冿細5 甯?p0.9 full锛?set -uo pipefail
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
