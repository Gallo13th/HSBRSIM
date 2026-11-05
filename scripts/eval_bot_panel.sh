#!/bin/bash
# 8 席全 bot 面板（无人类盘面）——canonical bot 口径，与 stage_monitor 的
# `--bot-panel-games` 完全一致（seed 620000 / move-guard 1 / cap 3 / repeat 2）。
#
# 用途：终点判定时把局数放大到 384，让「长且强」子集样本 n 从 ~7 提到 ~28
# （docs/B03_DESIGN.md §5.2 要求 n>=24 才算统计可读）。
#
# 用法：bash scripts/eval_bot_panel.sh <checkpoint> <run_tag> [games] [seed]
#   例：bash scripts/eval_bot_panel.sh runs/az_stage300m_b01/snapshots/step_004451/model.pt \
#                              b01_final_bot384 384 620000
# 环境变量：EVAL_DEVICE（默认 cuda:7）、EVAL_SEED（默认 620000）
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=rust/python:.
P=${PYTHON:-/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python}
CK=${1:?checkpoint required}
TAG=${2:?run tag required}
GAMES=${3:-384}
SEED=${4:-${EVAL_SEED:-620000}}
OUT=runs/eval_panel/$TAG.json
mkdir -p runs/eval_panel
$P scripts/quality_monitor.py \
  --checkpoint "$CK" --device "${EVAL_DEVICE:-cuda:7}" --games "$GAMES" --seed-base "$SEED" \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --longstrong-quantile 0.75 \
  > "$OUT" 2>"runs/eval_panel/$TAG.err"
$P - "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
w = d.get("weighted") or {}
ls = d.get("longstrong") or {}
print('tag', sys.argv[1].split('/')[-1],
      'games', d.get('games'),
      'guard', bool(d.get('move_guard')),
      'rank', round(d.get('mean_rank', 0), 3),
      'top4', round(d.get('top4', 0), 3),
      'win', round(d.get('win', 0), 3),
      '| w_rank', round(w.get('mean_rank', 0), 3),
      'w_win', round(w.get('win', 0), 3),
      '| ls_n', ls.get('n'),
      'ls_rank', ls.get('mean_rank'),
      'ls_win', ls.get('win'),
      'ls_thr', ls.get('thresholds'))
PY
