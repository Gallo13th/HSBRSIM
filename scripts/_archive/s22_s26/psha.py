import hashlib
import sys

import torch

sys.path.insert(0, "/home/data/users/gaoletian/projects/HSBRSIM")


def param_sha(path: str) -> str:
    try:
        payload = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        payload = torch.load(path, map_location="cpu")
    state = payload.get("model") if isinstance(payload, dict) else payload
    if state is None and isinstance(payload, dict):
        state = payload.get("state_dict") or payload
    h = hashlib.sha256()
    if hasattr(state, "state_dict"):
        state = state.state_dict()
    for k in sorted(state.keys()):
        v = state[k]
        if hasattr(v, "detach"):
            v = v.detach().cpu().contiguous()
            h.update(str(k).encode())
            h.update(v.numpy().tobytes())
    return h.hexdigest()


for p in sys.argv[1:]:
    print(p, param_sha(p))
