"""TavernArena 本地策略：把 HSBRSIM 的 30M checkpoint 接到竞技场观测。

竞技场（TavernArena, protocol v2）默认给 **v2 观测**：features=float32[4017]、
cards=int32[447]、action_mask=uint8[245]。协议明确 v1 的 3227/124 是 v2 的**前缀**，
因此本适配器：

1. 取 ``features[:3227]``、``cards[:124]``、``action_mask``（245）；
2. 把竞技场的卡牌下标（36.6.3 词表）通过 ``runs/arena/card_map.json`` 映射到我们
   训练时用的下标（37.0.0.255790 词表；实测竞技场 3,983 张卡的 id **100%** 都在我们的
   cards.json 里）；未识别的映射到 0（空槽）；
3. 用 entity 网络做一次前向，masked argmax 返回动作（与我们 C0 评测的 greedy 口径一致）。

模型/映射路径可用环境变量覆盖：
``ARENA_MODEL``（默认 ``runs/az_entity_kl_30m/model_30m.pt``）、
``ARENA_CARD_MAP``（默认 ``runs/arena/card_map.json``）、``ARENA_DEVICE``（默认 cuda:0）。

注意：这是一次**零样本跨版本**评估——模型训练在 37.0.0 数据上，竞技场跑 36.6.3；
词表 id 对齐不代表数值/机制完全一致，结果里的失误应部分归因于此。
"""

from __future__ import annotations

import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS_FLOATS = 3227
OBS_CARDS = 124
N_ACTIONS = 245

_state = {"model": None, "torch": None, "device": None, "map": None, "ckpt": None}


def _load() -> None:
    if _state["model"] is not None:
        return
    import torch
    from hsbg.az.train.model import load_checkpoint

    ckpt = os.environ.get("ARENA_MODEL",
                          os.path.join(ROOT, "runs/az_entity_kl_30m/model_30m.pt"))
    if not os.path.isfile(ckpt):
        raise FileNotFoundError(f"checkpoint 不存在: {ckpt}")
    dev = os.environ.get("ARENA_DEVICE", "cuda:0" if torch.cuda.is_available() else "cpu")
    if dev.startswith("cuda") and not torch.cuda.is_available():
        dev = "cpu"
    torch.set_num_threads(1)
    model, meta = load_checkpoint(ckpt, device=dev)
    model.eval()
    map_path = os.environ.get("ARENA_CARD_MAP", os.path.join(ROOT, "runs/arena/card_map.json"))
    with open(map_path, encoding="utf-8") as f:
        mapping = {int(k): int(v) for k, v in json.load(f)["mapping"].items()}
    _state.update({"model": model, "torch": torch, "device": dev,
                   "map": mapping, "ckpt": ckpt})
    print(f"[arena-agent] model={ckpt} device={dev} arch={meta.get('arch')} "
          f"card_map={len(mapping)} entries", flush=True)


def _prepare(observation):
    features = np.asarray(observation["features"], dtype=np.float32).reshape(-1)
    cards_raw = np.asarray(observation["cards"], dtype=np.int64).reshape(-1)
    mask = np.asarray(observation["action_mask"], dtype=bool).reshape(-1)
    if features.size < OBS_FLOATS or cards_raw.size < OBS_CARDS or mask.size != N_ACTIONS:
        raise ValueError(f"观测维度不符: features={features.size} cards={cards_raw.size} "
                         f"mask={mask.size}")
    cards = np.array([_state["map"].get(int(v), 0) for v in cards_raw[:OBS_CARDS]],
                     dtype=np.int64)
    return (np.ascontiguousarray(features[:OBS_FLOATS]), cards,
            np.ascontiguousarray(mask))


def act(observation, context):  # noqa: ANN001 - 竞技场回调签名
    """返回 0..244 的合法动作（masked argmax，无搜索）。"""
    _load()
    torch = _state["torch"]
    from hsbg.az.train.ppo import (forward_model, split_model_outputs)

    features, cards, mask = _prepare(observation)
    if not mask.any():
        return 0
    dev = torch.device(_state["device"])
    x = torch.from_numpy(features.reshape(1, -1)).to(dev)
    c = torch.from_numpy(cards.reshape(1, -1)).to(dev)
    m = torch.from_numpy(mask.reshape(1, -1)).to(dev)
    with torch.no_grad():
        logits, _rank_logits, _scalar = split_model_outputs(
            forward_model(_state["model"], x, c, m))
        logits = logits[0, :N_ACTIONS].masked_fill(~m[0], -float("inf"))
        action = int(torch.argmax(logits).item())
    return int(action) if mask[action] else int(np.flatnonzero(mask)[0])


def describe() -> dict:
    return {"checkpoint": _state.get("ckpt"),
            "device": _state.get("device"),
            "card_map_entries": len(_state.get("map") or {})}
