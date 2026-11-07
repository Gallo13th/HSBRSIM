#!/bin/bash
# B06 判读面板：150 / 250 / 300M 各跑一次 384 局 bot 面板（n_ls≈24）
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
for M in 150 250 300; do
  f=""
  for i in $(seq 1 1440); do
    f=$(ls runs/az_stage300m_b08/eval/ckpt_${M}0*.pt 2>/dev/null | head -1)
    [ -n "$f" ] && break
    sleep 30
  done
  if [ -z "$f" ]; then echo "[wait] ${M}M 超时 $(date '+%F %T')"; continue; fi
  echo "[run] $f -> b08_${M}M_bot384  $(date '+%F %T')"
  EVAL_DEVICE=cuda:7 bash scripts/eval_bot_panel.sh "$f" "b08_${M}M_bot384" 384 620000
  echo "[done] ${M}M $(date '+%F %T')"
done
echo "[all done] $(date '+%F %T')"
