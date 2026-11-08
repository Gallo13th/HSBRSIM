#!/bin/bash
# s22 璧风偣鍩虹嚎锛?.667M锛坰14-BC 钂搁锛夊湪 human 闈㈡澘 128 灞€ + 璐ㄩ噺闈㈡澘锛堝悓璁粌瀵规墜鍒嗗竷锛?set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
CKPT=runs/comp_lines/tiny_C_bc_s14/model_bc.pt
OUT=runs/az_entity_s22/baseline
mkdir -p "$OUT"

"$PY" scripts/human_panel_eval.py --checkpoint "$CKPT" --arch entity \
  --device cuda:6 --games 128 --seats 8 --seed-base 420000 --smoke \
  --quantile auto --bootstrap 1000 --baseline-bot 0 \
  --out "$OUT/human_start.json" > "$OUT/human_start.log" 2>&1
echo "human eval exit=$?"

"$PY" scripts/quality_monitor.py --checkpoint "$CKPT" --arch entity \
  --device cuda:6 --games 96 --seed-base 520000 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
  --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --out "$OUT/quality_start.json" > "$OUT/quality_start.log" 2>&1
echo "quality exit=$?"
