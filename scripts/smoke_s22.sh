#!/bin/bash
# s22 鍐掔儫锛氶獙璇?--value-warmup-iters / 0.667M checkpoint 鍔犺浇 / dpo+bc 杈呭姪 / 娴佹按绾垮叧闂矾寰?set -euo pipefail
cd /home/data/users/gaoletian/projects/HSBRSIM
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
export PYTHONPATH=rust/python:.
"$PY" scripts/train_entity_sync.py \
  --checkpoint runs/comp_lines/tiny_C_bc_s14/model_bc.pt \
  --arch entity --device cuda:7 --processes 2 --gpus 7 --threads 3 --games 24 \
  --sims 0 --epochs 1 --minibatch 256 --grad-accum 4 --amp bf16 \
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 200 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --human-board-fast-inject 1 --archetype-cache 0 --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-fidelity full --human-board-p 0.9 --human-board-seats 5 \
  --human-board-sample auto --human-board-set-tier 1 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.2 \
  --mirror-sample p75 --mirror-seat-random 1 \
  --archetype-bias-coef 0.5 --archetype-min-prob 0.6 \
  --bc-coef 0.004 --bc-type-weight 1.0 --bc-card-weight 0.5 --bc-batch 128 --bc-every 4 \
  --dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128 \
  --value-warmup-iters 3 --value-warmup-lr 1e-3 --value-warmup-minibatch 256 \
  --anchor-beta 0.1 --anchor-iterations 3 --anchor-amp 1 \
  --compile-train 0 --pipeline 0 --lockstep 1 --leaf-wait-ms 0 \
  --eval-every-decisions 0 --eval-panel human --eval-games 8 --eval-seats 8 \
  --seed 20100 --iterations 3 --minutes 10 --snapshot-every 2 --keep-snapshots 2 \
  --out runs/az_entity_s22_smoke 2>&1 | tail -60
echo "SMOKE_EXIT=$?"
