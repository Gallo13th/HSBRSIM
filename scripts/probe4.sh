#!/bin/bash
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
echo "=== run dirs matching bc/distill/small/tiny ==="
ls -d runs/*bc* runs/*distill* runs/*tiny* runs/*small* 2>/dev/null | head -30
echo
echo "=== ckpt_w8e4 arch ==="
PYTHONPATH=rust/python:. "$PY" - <<'PYEOF'
import torch
for p in ['runs/compound_bc/ckpt_w8e4.pt','runs/compound_bc/ckpt_dg1_128x2.pt','runs/compound_bc/ppo/rv_econ_tier/model.pt']:
    try:
        ck = torch.load(p, map_location='cpu', weights_only=False)
        sd = ck.get('state_dict') or ck.get('model')
        m = ck.get('meta') or {}
        print(p, '| nparams=', sum(v.numel() for v in sd.values()), '| meta=', {k:m.get(k) for k in ('arch','d_model','n_layers','n_heads','trained_by','decisions','size')})
    except Exception as e:
        print(p, 'ERR', e)
PYEOF
echo
echo "=== docs/COMP_LINES_TINY s14-BC section ==="
sed -n '355,370p' docs/COMP_LINES_TINY.md
