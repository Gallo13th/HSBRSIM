#!/bin/bash
# s22 phase3：从 **phase1 的 model.pt**（meta 正确：d128/n2/h4）续训，回到 --checkpoint 路径
# （该路径实测 kl≈0.002；--trainer-state 路径出现 kl≈0.037 的采集/learner 不一致，已弃用）。
# 保留 Lead 要求的 critic 周期性重热：--value-warmup-iters 5 --value-warmup-every 100。
set -euo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.

"$PY" scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s22/snapshots/step_000501/model.pt \
  --arch entity --d-model 128 --n-layers 2 --n-heads 4 \
  --device cuda:6 --processes 24 --gpus 3,4,5 --threads 3 --games 192 \
  --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 12000 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --human-board-fast-inject 1 --archetype-cache 0 --leaf-wait-ms 0 \
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
  --value-warmup-every 100 \
  --anchor-beta 0.1 --anchor-iterations 100000 --anchor-beta-tail 0.1 --anchor-amp 1 \
  --compile-train 1 --pipeline 1 --lockstep 1 \
  --eval-every-decisions 10000000 --eval-games 128 --eval-seats 8 \
  --eval-seed-base 420000 --eval-panel human --eval-human-quantile auto \
  --eval-async 1 --eval-device cuda:6 --eval-human-baseline-bot 0 --eval-drain 1 \
  --gpu-free-check 0 --seed 22000 \
  --iterations 20000 --stop-at-decisions 28600000 --minutes 480 \
  --snapshot-every 50 --keep-snapshots 6 \
  --out runs/az_entity_s22_ph3
