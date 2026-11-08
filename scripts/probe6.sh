#!/bin/bash
cd /home/data/users/gaoletian/projects/HSBRSIM || exit 1
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
echo "=== tiny_C_bc_s14 tree ==="
find runs/comp_lines/tiny_C_bc_s14 -maxdepth 2 -printf '%s %p\n' 2>/dev/null | sort -k2
echo
echo "=== tiny_C.log ==="
cat runs/comp_lines/tiny_C.log
echo
echo "=== arch of any ckpt there ==="
PYTHONPATH=rust/python:. "$PY" - <<'PYEOF'
import torch, glob
for p in sorted(glob.glob('runs/comp_lines/tiny_C_bc_s14/**/*.pt', recursive=True))[:12]:
    try:
        ck = torch.load(p, map_location='cpu', weights_only=False)
        sd = ck.get('state_dict') or ck.get('model')
        m = ck.get('meta') or {}
        print(p, '| nparams=', sum(v.numel() for v in sd.values()), '| meta=', {k: m.get(k) for k in ('arch','d_model','n_layers','n_heads','trained_by','decisions')})
    except Exception as e:
        print(p, 'ERR', type(e).__name__, e)
PYEOF
