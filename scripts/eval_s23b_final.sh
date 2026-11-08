#!/bin/bash
# s23b 缁堢偣锛?0.6M 绱锛夊洓鍙ｅ緞璇勬祴锛歜ot 闈㈡澘 / bot 鐜璐ㄩ噺 / 5 甯?p0.9 杩佺Щ / human 7 甯?set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
CK=runs/az_entity_s23b/model.pt
OUT=runs/az_entity_s23b/eval
mkdir -p "$OUT"

echo "[1/4] bot 闈㈡澘 (c0_gate 128)"
"$PY" scripts/c0_gate.py --checkpoint "$CK" --games 128 --seats 8 --device cuda:6 \
  --out "$OUT/c0_final.json" > "$OUT/c0_final.log" 2>&1
echo "exit=$?"

echo "[2/4] bot 鐜璐ㄩ噺 (96)"
"$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:6 \
  --games 96 --seed-base 520000 --human-board-p 0 --human-board-seats 0 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --out "$OUT/quality_final_bot.json" > "$OUT/quality_final_bot.log" 2>&1
echo "exit=$?"

echo "[3/4] 5 甯?p0.9 杩佺Щ (96)"
"$PY" scripts/quality_monitor.py --checkpoint "$CK" --arch entity --device cuda:6 \
  --games 96 --seed-base 520000 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
  --human-board-sample auto --human-board-set-tier 1 --human-board-fast-inject 1 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --out "$OUT/quality_final_p09.json" > "$OUT/quality_final_p09.log" 2>&1
echo "exit=$?"

echo "[4/4] human 7 甯?(128)"
"$PY" scripts/human_panel_eval.py --checkpoint "$CK" --arch entity --device cuda:6 \
  --games 128 --seats 8 --seed-base 420000 --smoke --quantile auto --bootstrap 1000 \
  --baseline-bot 0 --out "$OUT/human_final.json" > "$OUT/human_final.log" 2>&1
echo "exit=$?"
echo "ALL_DONE"
