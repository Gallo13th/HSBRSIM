#!/bin/bash
# upgrade-only bias A/B（Lead 批准）：0 / +0.25 / +0.5，各 256 局，5 席 p0.9 真实口径
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
CK=runs/az_entity_s23b/model.pt
OUT=runs/az_entity_s23b/bias
mkdir -p "$OUT"

for spec in "0:" "025:upgrade:0.25" "050:upgrade:0.5"; do
  TAG=${spec%%:*}
  BIAS=${spec#*:}
  echo "=== arm bias=${BIAS:-none} tag=$TAG $(date +%H:%M:%S)"
  if [ -n "$BIAS" ]; then
    "$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:7 \
      --games 256 --seed-base 520000 --action-logit-bias "$BIAS" \
      --human-boards data/real_library/library_real_quasi_full.jsonl \
      --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
      --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
      --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
      --out "$OUT/bias_u$TAG.json" > "$OUT/bias_u$TAG.log" 2>&1
  else
    "$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:7 \
      --games 256 --seed-base 520000 \
      --human-boards data/real_library/library_real_quasi_full.jsonl \
      --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
      --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
      --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
      --out "$OUT/bias_u$TAG.json" > "$OUT/bias_u$TAG.log" 2>&1
  fi
  echo "exit=$? $(date +%H:%M:%S)"
done
echo "BIAS_AB_DONE"
