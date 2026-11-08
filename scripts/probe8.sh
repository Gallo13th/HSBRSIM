#!/bin/bash
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
echo "=== model.train() in train stack ==="
grep -rn '\.train()' hsbg/az/train/ppo.py hsbg/az/train/ppo_trainer.py hsbg/az/train/process_pool.py hsbg/az/train/parallel_collect.py | head -20
echo
echo "=== ckpt load region in train_entity_sync ==="
sed -n '1060,1125p' scripts/train_entity_sync.py
echo
echo "=== dropout in entity_model ==="
grep -n 'dropout' hsbg/az/train/entity_model.py | head -10
