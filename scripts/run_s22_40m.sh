#!/bin/bash
# s22锛?.667M entity锛坉128脳2脳4heads锛夊湪**瀹屾暣瀵瑰眬**鍋?RL锛屽厛 40M decisions 楠岃瘉銆?# 璧风偣 = runs/comp_lines/tiny_C_bc_s14/model_bc.pt锛坰14 鈫?0.667M 鐨?BC 300k 钂搁锛?#        s14 鏈綋鏄?d384脳8 = 16.95M锛屾灦鏋勪笉鍏煎锛屾棤娉曠洿鎺ュ姞杞斤級銆?# 璧勬簮锛歛ctors GPU 3/4/5 + learner GPU 6锛?4 杩涚▼ 脳 3 绾跨▼ = 72 绾跨▼锛堚墹76锛夛紱
#       eval(寮傛) 澶嶇敤 learner 鍗?cuda:6锛堜笉棰濆鍗?GPU锛夈€?set -euo pipefail
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
