#!/bin/bash
# 诊断：从 step_000501 trainer state 续训 2 个 iteration（全新 out 目录、串行、无 compile），
# 目的是看 pre-update approx_kl 是否仍有 0.037（排查采集/learner 权重不一致）。
set -uo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
D=/tmp/s22/diag
rm -rf "$D"; mkdir -p "$D"
cp runs/az_entity_s22/snapshots/step_000501/trainer.pt "$D/trainer.pt"

"$PY" scripts/train_entity_sync.py \
  --trainer-state "$D/trainer.pt" \
  --arch entity --d-model 128 --n-layers 2 --n-heads 4 \
  --device cuda:7 --processes 2 --gpus 7 --threads 3 --games 24 \
  --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 12000 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --human-board-fast-inject 1 --leaf-wait-ms 0 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-fidelity full --human-board-p 0.9 --human-board-seats 5 \
  --human-board-sample auto --human-board-set-tier 1 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.2 \
  --mirror-sample p75 --mirror-seat-random 1 \
  --archetype-bias-coef 0.5 --archetype-min-prob 0.6 \
  --bc-coef 0.004 --bc-type-weight 1.0 --bc-card-weight 0.0 --bc-batch 128 --bc-every 4 \
  --bc-compile 1 \
  --dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128 \
  --value-warmup-iters 5 --value-warmup-lr 1e-3 --value-warmup-minibatch 1024 \
  --anchor-beta 0.1 --anchor-iterations 100000 --anchor-beta-tail 0.1 --anchor-amp 1 \
  --compile-train 0 --pipeline 0 --lockstep 1 \
  --eval-every-decisions 0 --eval-panel human \
  --gpu-free-check 0 --seed 22000 \
  --iterations 2 --minutes 12 \
  --out "$D/run" 2>&1 | grep -E "ppo\]|iter |resume\]|net\] arch|value-warmup" | cut -c1-200
echo "DIAG_DONE"
