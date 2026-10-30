"""TavernArena 本地策略：把 HSBRSIM 的 checkpoint 接到竞技场观测。

竞技场（TavernArena, protocol v2）默认给 **v2 观测**：features=float32[4017]、
cards=int32[447]、action_mask=uint8[245]。协议明确 v1 的 3227/124 是 v2 的**前缀**，
因此本适配器：

1. 取 ``features[:3227]``、``cards[:124]``、``action_mask``（245）；
2. 把竞技场的卡牌下标（36.6.3 词表）通过 ``runs/arena/card_map.json`` 映射到我们
   训练时用的下标（37.0.0.255790 词表；实测竞技场 3,983 张卡的 id **100%** 都在我们的
   cards.json 里）；未识别的映射到 0（空槽）；
3. 用 entity 网络做一次前向，masked argmax 返回动作（与我们 C0 评测的 greedy 口径一致）。

动作索引 **原样透传**：竞技场 manifest 声明的 245 动作布局与 hsbg_engine 逐字节相同
（``action_layout_sha256 = be2e9758…e674bd``，含 196..244 的 49 个 ``Move { from, to }``），
所以本地选出的换位动作不需要任何转换。见 docs/POSITION_ACTION_AUDIT.md。

模型/映射路径可用环境变量覆盖：
``ARENA_MODEL``（默认 ``runs/az_entity_kl_30m/model_30m.pt``）、
``ARENA_CARD_MAP``（默认 ``runs/arena/card_map.json``）、``ARENA_DEVICE``（默认 cuda:0）、
``ARENA_ACTION_LOG``（默认空=关闭；设为文件路径后每个决策追加一行 JSON：动作/动作段/
换位合法位数/累计计数，用于线上核验换位是否被选中、竞技场掩码是否给位）。

注意：这是一次**零样本跨版本**评估——模型训练在 37.0.0 数据上，竞技场跑 36.6.3；
词表 id 对齐不代表数值/机制完全一致，结果里的失误应部分归因于此。
"""

from __future__ import annotations

import atexit
import json
import os

import numpy as np

from hsbg.env.action_space_std import A_MOVE, N_BOARD, segment_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS_FLOATS = 3227
OBS_CARDS = 124
N_ACTIONS = 245
MOVE_HI = A_MOVE + N_BOARD * N_BOARD  # 245

_state = {"model": None, "torch": None, "device": None, "map": None, "ckpt": None,
          "norm_mean": None, "norm_std": None, "counters": None, "action_log": ""}


def _counters() -> dict:
    """懒初始化并返回活计数器 dict（act 原地累加；测试直接塞 _state 也能用）。"""
    if _state.get("counters") is None:
        _state["counters"] = {"decisions": 0, "segments": {},
                              "move_legal_decisions": 0, "move_selected": 0}
    return _state["counters"]


def _stats() -> dict:
    """本次进程的动作段计数快照（供 describe / 退出摘要）。"""
    return json.loads(json.dumps(_counters()))


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
                   "map": mapping, "ckpt": ckpt,
                   # 训练用 norm stats（多数 checkpoint 没有；有则必须一致，否则前向口径错）
                   "norm_mean": meta.get("norm_mean"),
                   "norm_std": meta.get("norm_std"),
                   "counters": {"decisions": 0, "segments": {},
                                "move_legal_decisions": 0, "move_selected": 0},
                   "action_log": os.environ.get("ARENA_ACTION_LOG", "").strip()})
    print(f"[arena-agent] model={ckpt} device={dev} arch={meta.get('arch')} "
          f"card_map={len(mapping)} entries "
          f"norm={'on' if _state['norm_mean'] is not None else 'off'} "
          f"action_log={_state['action_log'] or 'off'}", flush=True)
    if _state["action_log"]:
        atexit.register(_log_summary)


def _log_summary() -> None:
    """退出时把动作段计数打到 stdout（``--games N`` 跑完即可核对换位占比）。"""
    try:
        print("[arena-agent] action stats: " +
              json.dumps(_stats(), ensure_ascii=False, sort_keys=True), flush=True)
    except Exception:  # noqa: BLE001 - 诊断输出绝不影响对局
        pass


def _prepare(observation):
    features = np.asarray(observation["features"], dtype=np.float32).reshape(-1)
    cards_raw = np.asarray(observation["cards"], dtype=np.int64).reshape(-1)
    mask = np.asarray(observation["action_mask"], dtype=bool).reshape(-1)
    if features.size < OBS_FLOATS or cards_raw.size < OBS_CARDS or mask.size != N_ACTIONS:
        raise ValueError(f"观测维度不符: features={features.size} cards={cards_raw.size} "
                         f"mask={mask.size}")
    cards = np.array([_state["map"].get(int(v), 0) for v in cards_raw[:OBS_CARDS]],
                     dtype=np.int64)
    x = features[:OBS_FLOATS]
    if _state.get("norm_mean") is not None:
        x = x - _state["norm_mean"]
    if _state.get("norm_std") is not None:
        x = x / _state["norm_std"]
    return np.ascontiguousarray(x, dtype=np.float32), cards, np.ascontiguousarray(mask)


def act(observation, context):  # noqa: ANN001 - 竞技场回调签名
    """返回 0..244 的合法动作（masked argmax，无搜索）。

    换位（196..244）与其它动作同权：掩码里给位就参与 argmax，返回的就是**同一个索引**
    （竞技场动作布局与本地逐字节一致，无需映射）。``ARENA_ACTION_LOG`` 打开时逐决策落盘。
    """
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
    action = int(action) if mask[action] else int(np.flatnonzero(mask)[0])

    # ── 诊断（默认零影响：只在 ARENA_ACTION_LOG 非空时写）──
    seg = segment_of(action)
    stats = _counters()
    stats["decisions"] += 1
    stats["segments"][seg] = int(stats["segments"].get(seg, 0)) + 1
    move_legal = int(mask[A_MOVE:MOVE_HI].sum())
    if move_legal > 0:
        stats["move_legal_decisions"] += 1
    if seg == "move":
        stats["move_selected"] += 1
    if _state.get("action_log"):
        ctx = context or {}
        rec = {"match_id": ctx.get("match_id"), "seat": ctx.get("seat"),
               "turn": ctx.get("turn"), "actions_used": ctx.get("actions_used"),
               "action": action, "segment": seg,
               "mask_legal": int(mask.sum()),
               "move_legal_bits": move_legal,
               "counter": stats["decisions"]}
        try:
            with open(_state["action_log"], "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return action


def describe() -> dict:
    return {"checkpoint": _state.get("ckpt"),
            "device": _state.get("device"),
            "card_map_entries": len(_state.get("map") or {}),
            "norm_stats": _state.get("norm_mean") is not None,
            "action_log": _state.get("action_log") or None,
            "stats": _stats() if _state.get("counters") else None}
