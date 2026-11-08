#!/bin/bash
# s26b锛氳缁冧晶鍏堥獙鑷傦紙D3+T3锛夆€斺€斿鍔卞洖鍒?s25 鍩虹嚎锛岃繃绋嬮」鍏ㄥ叧
# 璧风偣 s25 鏉冮噸锛?0M锛涘垽鎹細5脳p0.9 S15 鈮?50銆乬oldens 鈮?.8銆乼5+ 韬潗鍗犳瘮 鈮?0%
set -euo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
ulimit -n 65536 2>/dev/null || true

"$PY" scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s25/model.pt \
  --arch entity --d-model 128 --n-layers 2 --n-heads 4 \
  --device cuda:6 --processes 24 --gpus 3,4,5 --threads 3 --games 384 \
  --ipc-mode shm --records-dtype fp32 \
  --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 12000 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --rank-utility-coef 0 --win-only-reward 1.0 \
  --strength-reward-coef 0.7 \
  --tier-target-coef 1.0 --tier-bonus 0.3 --tier-penalty 0.02 \
  --tier-target-table 7:4,9:5,10:5,12:6 \
  --upgrade-reward 0.05 \
  --discover-bc-coef 1e-5 --triple-bc-coef 1e-5 --bc-ce-norm 1 --bc-warmup-decisions 2000000 --bc-guard-ratio 0.3 \
  --human-board-seats 0 --mirror-seats 0 \
  --human-board-fast-inject 1 --archetype-cache 0 --leaf-wait-ms 0 \
  --archetype-bias-coef 0.5 --archetype-min-prob 0.6 \
  --bc-coef 0.004 --bc-type-weight 1.0 --bc-card-weight 0.0 --bc-batch 128 --bc-every 4 \
  --bc-compile 1 \
  --dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128 \
  --value-warmup-iters 5 --value-warmup-lr 1e-3 --value-warmup-minibatch 1024 \
  --value-warmup-every 100 \
  --anchor-beta 0.1 --anchor-iterations 100000 --anchor-beta-tail 0.1 --anchor-amp 1 \
  --compile-train 1 --pipeline 1 --lockstep 1 \
  --eval-every-decisions 10000000 --eval-games 128 --eval-seats 8 \
  --eval-seed-base 420000 --eval-panel both --eval-human-quantile auto \
  --eval-async 1 --eval-device cuda:6 --eval-human-baseline-bot 0 --eval-drain 1 \
  --gpu-free-check 0 --seed 37000 \
  --iterations 20000 --stop-at-decisions 10000000 --minutes 180 \
  --snapshot-every 50 --keep-snapshots 6 \
  --out runs/az_entity_s26d
