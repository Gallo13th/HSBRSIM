#!/bin/bash
# s22 寤変环灏忓疄楠岋細1M decisions锛屽悓涓€ ctrl-20M 璧风偣銆佸悓涓€璇剧▼锛? 甯?p0.75锛?#   $1 = tag锛堣緭鍑虹洰褰?runs/az_entity_s22/$1锛?#   $2 = GPU
#   $3.. = 棰濆鐨勮缁冨弬鏁帮紙渚嬪 --upgrade-reward 0.05锛?set -euo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
TAG="$1"; GPU="$2"; shift 2

"$PY" scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s22_ctrl/model.pt \
  --arch entity --d-model 128 --n-layers 2 --n-heads 4 \
  --device "cuda:$GPU" --processes 6 --gpus "$GPU" --threads 2 --games 48 \
  --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 12000 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --tier-target-coef 1.0 --tier-target-table 7:4,9:5,10:5,12:6 \
  --human-board-fast-inject 1 --archetype-cache 0 --leaf-wait-ms 0 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-fidelity full --human-board-p 0.75 --human-board-seats 3 \
  --human-board-sample auto --human-board-set-tier 1 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.2 \
  --mirror-sample p75 --mirror-seat-random 1 \
  --archetype-bias-coef 0.5 --archetype-min-prob 0.6 \
  --bc-coef 0.004 --bc-type-weight 1.0 --bc-card-weight 0.0 --bc-batch 128 --bc-every 4 \
  --bc-compile 0 \
  --dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128 \
  --value-warmup-iters 5 --value-warmup-lr 1e-3 --value-warmup-minibatch 1024 \
  --value-warmup-every 100 \
  --anchor-beta 0.1 --anchor-iterations 100000 --anchor-beta-tail 0.1 --anchor-amp 0 \
  --compile-train 0 --pipeline 0 --lockstep 1 \
  --eval-every-decisions 0 --eval-panel human \
  --gpu-free-check 0 --seed "${SEED:-25000}" \
  --iterations 20000 --stop-at-decisions 1000000 --minutes 90 \
  --snapshot-every 100 --keep-snapshots 4 \
  --out "runs/az_entity_s22/$TAG" "$@"
