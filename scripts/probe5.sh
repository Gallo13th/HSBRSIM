#!/bin/bash
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
echo "=== runs/small_expert* tree ==="
find runs/small_expert runs/small_expert_distill -maxdepth 3 -printf '%s %p\n' 2>/dev/null | sort -k2 | head -40
echo
echo "=== SMALL_EXPERT_DISTILL.md head ==="
sed -n '1,60p' docs/SMALL_EXPERT_DISTILL.md
echo
echo "=== SMALL_EXPERT_CURRICULUM.md head ==="
sed -n '1,40p' docs/SMALL_EXPERT_CURRICULUM.md
