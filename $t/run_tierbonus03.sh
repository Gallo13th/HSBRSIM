#!/bin/bash
# 廉价小实验（Lead 04:40）：只把 tier-target **bonus 0.15 → 0.3**（coef 仍 1.0、penalty 0.02 不动），
# 与 ctrl2 同一起点（ctrl 20M 权重）、同一课程（3 席 p0.75），跑 1M decisions 看 tier 是否动。
# 不占训练卡：GPU 7 + 6 进程 × 2 线程（临时；主训练仍是 3/4/5+6、72 线程）。
set -euo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.

"$PY" scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s22_ctrl/model.pt \
  --arch entity --d-model 128 --n-layers 2 --n-heads 4 \
  --device cuda:7 --processes 6 --gpus 7 --threads 2 --games 48 \
  --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 12000 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --tier-target-coef 1.0 --tier-bonus 0.3 --tier-penalty 0.02 \
  --tier-target-table 7:4,9:5,10:5,12:6 \
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
  --gpu-free-check 0 --seed 25000 \
  --iterations 20000 --stop-at-decisions 1000000 --minutes 90 \
  --snapshot-every 100 --keep-snapshots 4 \
  --out runs/az_entity_s22/tierbonus03
