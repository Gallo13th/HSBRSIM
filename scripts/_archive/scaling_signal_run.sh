#!/usr/bin/env bash
# 缩放信号探测：全部 arm 的顺序驱动（离线，纯 CPU；不训练、不占 GPU）
set -u
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
export PYTHONPATH=rust/python:.
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
CKPT=runs/scaling_signal/ckpt/s15_step301.pt
OUT=runs/scaling_signal/rollouts

echo "=== start $(date -Is)"
# 1) 真实经济（1x）：200 局
$PY scripts/scaling_signal_probe.py --checkpoint "$CKPT" --device cpu \
    --games 200 --workers 10 --tag real --seed-base 880000 --out-dir "$OUT" \
    && echo "[ok] real $(date -Is)"
# 2) ∞金币课程（gold=99，训练同口径 cap 40）：200 局（前 100 局 = 与 real 配对的子集）
$PY scripts/scaling_signal_probe.py --checkpoint "$CKPT" --device cpu \
    --games 200 --workers 10 --tag gold99 --gold 99 --seed-base 880000 --out-dir "$OUT" \
    && echo "[ok] gold99 $(date -Is)"
# 3) ∞金币 + 更松动作预算（cap 120，ceiling-probe 口径）：100 局
$PY scripts/scaling_signal_probe.py --checkpoint "$CKPT" --device cpu \
    --games 100 --workers 10 --tag gold99_cap120 --gold 99 --max-actions-per-turn 120 \
    --seed-base 880000 --out-dir "$OUT" \
    && echo "[ok] gold99_cap120 $(date -Is)"
# 4) 金币剂量曲线（「课程该开多大」）：gold ∈ {12,15,20,30,50,99} × 60 局
for g in 12 15 20 30 50 99; do
    $PY scripts/scaling_signal_probe.py --checkpoint "$CKPT" --device cpu \
        --games 60 --workers 10 --tag "dose_g${g}" --gold "$g" --seed-base 882000 \
        --out-dir "$OUT" && echo "[ok] dose_g${g} $(date -Is)"
done
echo "=== done $(date -Is)"
