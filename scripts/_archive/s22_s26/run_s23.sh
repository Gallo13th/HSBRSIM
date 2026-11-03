#!/bin/bash
# s23（用户决策）：**8 席全 bot** + 只奖励夺冠 + 密集强度项
# 相对 s22 的变化：
#   --human-board-seats 0 --mirror-seats 0         ⇒ 8 席全 bot（无人类战团/无镜像）
#   --rank-utility-coef 0 + --win-only-reward 1    ⇒ 终局只有第 1 名 +1，其余 0
#   --strength-reward-coef 0.7                     ⇒ 每回合 ΔL(Σ) 密集项（tanh 前同一曲线）
#   --tier-target-coef 1.0 --tier-bonus 0.3        ⇒ 升本（bonus 从 0.15 抬到 0.3）
#   --upgrade-reward 0.05                          ⇒ 保留
# 其余（d128×2、move-guard、lr 1.2e-6、β≡0.1、value-warmup 5/100、compile/pipeline/lockstep）不变。
# 判据：bot 面板 top1 ≥15% 且 t15 Σ ≥600 且 tier@t15 ≥5。
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
  --rank-utility-coef 0 --win-only-reward 1.0 --strength-reward-coef 0.7 \
  --tier-target-coef 1.0 --tier-bonus 0.3 --tier-penalty 0.02 \
  --tier-target-table 7:4,9:5,10:5,12:6 \
  --upgrade-reward 0.05 \
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
  --gpu-free-check 0 --seed 30000 \
  --iterations 20000 --stop-at-decisions 20000000 --minutes 300 \
  --snapshot-every 50 --keep-snapshots 6 \
  --out runs/az_entity_s23
