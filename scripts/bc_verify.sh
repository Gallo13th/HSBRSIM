#!/bin/bash
# 杈呭姪 BC 楠岃瘉锛?# A) coef=0 涓ゆ锛堝悓 seed 2 iter锛夆啋 鍙傛暟 sha 蹇呴』鐩稿悓
# B) coef=0.05/0.05 鈫?sha 涓嶅悓锛屼笖鏃ュ織閲?bc_discover / bc_triple loss 瀛樺湪骞朵笅闄?set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
ulimit -n 65536 2>/dev/null || true

run () {
  local out="$1"; local dc="$2"; local tc="$3"; local iters="$4"
  rm -rf "$out"
  "$PY" scripts/train_entity_sync.py \
    --checkpoint runs/az_entity_s25/model.pt \
    --arch entity --d-model 128 --n-layers 2 --n-heads 4 \
    --device cuda:7 --processes 2 --gpus 7 --threads 3 --games 48 \
    --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
    --lr 1.2e-6 --clip 0.2 --target-kl 0.02 --lam 0.995 --entropy-coef 0.001 \
    --pi-coef 0 --shaping-coef 0 --move-guard 1 --rank-utility-coef 0 \
    --win-only-reward 1.0 --strength-reward-coef 0.7 \
    --tier-target-coef 1.0 --tier-bonus 0.3 --upgrade-reward 0.05 \
    --discover-bc-coef "$dc" --triple-bc-coef "$tc" \
    --human-board-seats 0 --mirror-seats 0 --bc-coef 0 --dpo-coef 0 \
    --compile-train 0 --pipeline 0 --lockstep 1 \
    --eval-every-decisions 0 --seed 77 --iterations "$iters" --minutes 15 \
    --out "$out" > "$out.log" 2>&1
  echo "run $out exit=$? $(date +%H:%M:%S)"
}

run /tmp/s22/bcA 0.0 0.0 2
run /tmp/s22/bcB 0.0 0.0 2
run /tmp/s22/bcC 0.05 0.05 8
echo "=== param sha ==="
"$PY" /tmp/s22/psha.py /tmp/s22/bcA/model.pt /tmp/s22/bcB/model.pt /tmp/s22/bcC/model.pt
echo "=== bc losses (arm C) ==="
grep -o "bc_discover=[0-9.]*" /tmp/s22/bcC.log | head -8
grep -o "bc_triple=[0-9.]*" /tmp/s22/bcC.log | head -8
echo BCTEST_DONE
