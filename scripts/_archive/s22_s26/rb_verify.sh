#!/bin/bash
# 接线验证：
# A) collect bias = 0 两次（同 seed）→ 参数 sha 必须相同（逐位等价 & 确定性）
# B) collect bias = 3.0 → sha 应不同（证明先验真的生效）
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
ulimit -n 65536 2>/dev/null || true

run () {
  local out="$1"; local db="$2"; local tb="$3"
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
    --collect-discover-bias "$db" --collect-triple-bias "$tb" \
    --human-board-seats 0 --mirror-seats 0 --bc-coef 0 --dpo-coef 0 \
    --compile-train 0 --pipeline 0 --lockstep 1 \
    --eval-every-decisions 0 --seed 77 --iterations 2 --minutes 10 \
    --out "$out" > "$out.log" 2>&1
  echo "run $out exit=$? $(date +%H:%M:%S)"
}

run /tmp/s22/rbA 0.0 0.0
run /tmp/s22/rbB 0.0 0.0
run /tmp/s22/rbC 3.0 3.0
echo "=== param sha ==="
"$PY" /tmp/s22/psha.py /tmp/s22/rbA/model.pt /tmp/s22/rbB/model.pt /tmp/s22/rbC/model.pt
grep -h "collect_bias" /tmp/s22/rbA.log /tmp/s22/rbC.log 2>/dev/null | head -4
echo RBTEST_DONE
