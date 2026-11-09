#!/bin/bash
# B11 判读面板：150 / 250 / 300M 的 384 局 bot 面板 + 300M 的 768 局终评 + human 96 局
# 注意：relabel 后的 ckpt 名不一定以 "M0" 开头（例如 250M 点是 ckpt_258146613.pt），
# 所以按"decisions >= M 的最小全局 ckpt"选取。
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
export HSBRSIM_FORCE_UPGRADE=1
export HSBRSIM_BAN_TRINKETS=BG36_MagicItem_414
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python

pick() {  # $1 = M（单位百万）
  ls -1 runs/az_stage300m_b12/eval/ckpt_[0-9]*.pt 2>/dev/null | $PY -c "
import sys,re
M=$1*1000000
best=None
for line in sys.stdin:
    m=re.search(r'ckpt_0*([0-9]+)\\.pt', line.strip())
    if not m: continue
    d=int(m.group(1))
    if d>=M and (best is None or d<best[0]): best=(d,line.strip())
print(best[1] if best else '')
"
}

for M in 150 250 300; do
  tag="b12_${M}M_bot384"; [ "$M" = "300" ] && tag="b12_300M_bot768"
  games=384; [ "$M" = "300" ] && games=768
  out="runs/eval_panel/${tag}.json"
  if [ -s "$out" ]; then echo "[skip] ${M}M 已有 $out"; continue; fi
  f=""
  for i in $(seq 1 1440); do
    f=$(pick "$M")
    [ -n "$f" ] && break
    sleep 30
  done
  if [ -z "$f" ]; then echo "[wait] ${M}M 超时 $(date '+%F %T')"; continue; fi
  echo "[run] $f -> $tag (${games} 局) $(date '+%F %T')"
  EVAL_DEVICE=cuda:7 bash scripts/eval_bot_panel.sh "$f" "$tag" "$games" 620000
  echo "[done] ${M}M $(date '+%F %T')"
  if [ "$M" = "300" ]; then
    echo "[run] human 96 局 $(date '+%F %T')"
    EVAL_DEVICE=cuda:1 bash scripts/eval_panel.sh "$f" "b12_300M_human96"
    echo "[done] human $(date '+%F %T')"
  fi
done
echo "[all done] $(date '+%F %T')"
