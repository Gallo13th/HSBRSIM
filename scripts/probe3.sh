#!/bin/bash
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
echo "=== .pt under runs/compound_bc (sizes) ==="
find runs/compound_bc -name '*.pt' -printf '%s %p\n' 2>/dev/null | sort -n | head -20
echo
echo "=== docs mentioning 0.667M ==="
grep -rln '0\.667M\|0.667 M\|667k' docs/ | head -10
grep -rn '0\.667M' docs/*.md | head -20
echo
echo "=== small entity arch spec in docs ==="
grep -rn 'd-model 128\|d_model=128\|d-model=128' docs/ scripts/ hsbg/ 2>/dev/null | grep -v Binary | head -10
