#!/usr/bin/env bash
# v2：与 v1 同 seed 重跑 real/gold99，额外记录 7 席对手当前战团（阈值/相对强度分析用）
set -u
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
export PYTHONPATH=rust/python:.
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
CKPT=runs/scaling_signal/ckpt/s15_step301.pt
OUT=runs/scaling_signal/rollouts
echo "=== v2 start $(date -Is)"
$PY scripts/scaling_signal_probe.py --checkpoint "$CKPT" --device cpu \
    --games 200 --workers 8 --tag real_opp --seed-base 880000 --out-dir "$OUT" \
    --record-opponents 1 && echo "[ok] real_opp $(date -Is)"
$PY scripts/scaling_signal_probe.py --checkpoint "$CKPT" --device cpu \
    --games 200 --workers 8 --tag gold99_opp --gold 99 --seed-base 880000 --out-dir "$OUT" \
    --record-opponents 1 && echo "[ok] gold99_opp $(date -Is)"
echo "=== v2 done $(date -Is)"
