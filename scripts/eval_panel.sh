#!/bin/bash
# 固定评测面板（唯一口径）：真实库 5 席 p0.9 / full fidelity / p75 / 96 局 / seed 520000
# 用法：bash scripts/eval_panel.sh <checkpoint> <run_tag> [games]
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=rust/python:.
P=${PYTHON:-/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python}
CK=${1:?checkpoint required}
TAG=${2:?run tag required}
GAMES=${3:-96}
OUT=runs/eval_panel/$TAG.json
mkdir -p runs/eval_panel
$P scripts/quality_monitor.py \
  --checkpoint "$CK" --device "${EVAL_DEVICE:-cuda:7}" --games "$GAMES" --seed-base "${EVAL_SEED:-520000}" \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-seats 5 --human-board-p 0.9 --human-board-fidelity full \
  --human-board-sample p75 --human-board-set-tier 1 \
  > "$OUT" 2>"runs/eval_panel/$TAG.err"
$P - "$OUT" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print('tag',sys.argv[1].split('/')[-1],
      'rank',round(d.get('mean_rank',0),3),
      'top4',round(d.get('top4',0),3),
      'strength',d.get('death_strength_p50'),
      'tier4+',round(d.get('tier_ge4_ratio') or 0,3),
      'survive12',round(d.get('survive_t12_ratio') or 0,3))
PY
