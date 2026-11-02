#!/bin/bash
# s22 动态课程臂（dyn）：Lead 07:00 批准
# 规则（写进脚本 --dyn-curriculum 1）：起点 2 席 p0.75；每当**真实强度口径**（5 席 p0.9 面板
# 的 t15 Σ p50）比上一次评测提升 ≥10% 就回加一席（2→3→4→5）；回加后若回退 >10% 则退回一档
# 并保持 10M；上限 5 席。主判据 = 真实口径 S15（训练剂量只作参考）。
# 保留 upgrade-reward 0.05 + tier-target 1.0；起点 = ctrl3 **10M 峰值**权重（不用 20M 退化点）。
set -euo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.

"$PY" scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s22/ctrl3/eval/ckpt_010006112.pt \
  --arch entity --d-model 128 --n-layers 2 --n-heads 4 \
  --device cuda:6 --processes 24 --gpus 3,4,5 --threads 3 --games 192 \
  --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 12000 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --tier-target-coef 1.0 --tier-bonus 0.15 --tier-penalty 0.02 \
  --tier-target-table 7:4,9:5,10:5,12:6 \
  --upgrade-reward 0.05 \
  --dyn-curriculum 1 --dyn-start-seats 2 --dyn-max-seats 5 --dyn-p 0.75 \
  --dyn-threshold 0.10 --dyn-hold-decisions 10000000 --dyn-quality-games 96 \
  --human-board-fast-inject 1 --archetype-cache 0 --leaf-wait-ms 0 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-fidelity full --human-board-p 0.75 --human-board-seats 2 \
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
  --gpu-free-check 0 --seed 29000 \
  --iterations 20000 --stop-at-decisions 20000000 --minutes 300 \
  --snapshot-every 50 --keep-snapshots 6 \
  --out runs/az_entity_s22/dyn
