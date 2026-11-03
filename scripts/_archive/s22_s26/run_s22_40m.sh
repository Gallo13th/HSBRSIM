#!/bin/bash
# s22：0.667M entity（d128×2×4heads）在**完整对局**做 RL，先 40M decisions 验证。
# 起点 = runs/comp_lines/tiny_C_bc_s14/model_bc.pt（s14 → 0.667M 的 BC 300k 蒸馏；
#        s14 本体是 d384×8 = 16.95M，架构不兼容，无法直接加载）。
# 资源：actors GPU 3/4/5 + learner GPU 6；24 进程 × 3 线程 = 72 线程（≤76）；
#       eval(异步) 复用 learner 卡 cuda:6（不额外占 GPU）。
set -euo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.

"$PY" scripts/train_entity_sync.py \
  --checkpoint runs/comp_lines/tiny_C_bc_s14/model_bc.pt \
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
  --value-warmup-iters 60 --value-warmup-lr 1e-3 --value-warmup-minibatch 1024 \
  --anchor-beta 0.1 --anchor-iterations 100000 --anchor-beta-tail 0.1 --anchor-amp 1 \
  --compile-train 1 --pipeline 1 --lockstep 1 \
  --eval-every-decisions 10000000 --eval-games 128 --eval-seats 8 \
  --eval-seed-base 420000 --eval-panel human --eval-human-quantile auto \
  --eval-async 1 --eval-device cuda:6 --eval-human-baseline-bot 0 --eval-drain 1 \
  --gpu-free-check 0 --seed 22000 \
  --iterations 20000 --stop-at-decisions 40000000 --minutes 480 \
  --snapshot-every 50 --keep-snapshots 4 \
  --out runs/az_entity_s22
