#!/bin/bash
# s26 鍒ゆ嵁涓夊彛寰勶細bot 鐜锛坓oldens / t5+ 韬潗鍗犳瘮 / S15锛? 5 甯?p0.9 S15
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.:scripts
CK=runs/az_entity_s26/eval/ckpt_010026871.pt
OUT=runs/az_entity_s26/eval

echo "=== s26 collector(bot) 150 games $(date +%H:%M:%S)"
"$PY" scripts/chain_collector.py --checkpoint "$CK" --games 150 --device cuda:6 \
  --out-dir "$OUT" --tag s26 > "$OUT/collect_s26.log" 2>&1
echo "collector exit=$? $(date +%H:%M:%S)"

echo "=== s26 quality 5x p0.9 96 games $(date +%H:%M:%S)"
"$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:6 \
  --games 96 --seed-base 520000 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
  --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --out "$OUT/q5p09_s26.json" > "$OUT/q5p09_s26.log" 2>&1
echo "quality exit=$? $(date +%H:%M:%S)"
echo S26_PANELS_DONE
