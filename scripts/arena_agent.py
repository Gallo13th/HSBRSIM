"""TavernArena 本地策略：把 HSBRSIM 的 checkpoint 接到竞技场观测。

竞技场（TavernArena, protocol v2）默认给 **v2 观测**：features=float32[4017]、
cards=int32[447]、action_mask=uint8[245]。协议明确 v1 的 3227/124 是 v2 的**前缀**，
因此本适配器：

1. 取 ``features[:3227]``、``cards[:124]``、``action_mask``（245）；
2. 把竞技场的卡牌下标（36.6.3 词表）通过 ``runs/arena/card_map.json`` 映射到我们
   训练时用的下标（37.0.0.255790 词表；实测竞技场 3,983 张卡的 id **100%** 都在我们的
   cards.json 里）；未识别的映射到 0（空槽）；
3. 用 entity 网络做一次前向，masked argmax 返回动作（与我们 C0 评测的 greedy 口径一致）；
4. **换位去抖守卫**：用训练侧 ``hsbg/az/train/move_guard.py`` 的同一套规则先改写 mask
   （逆换位屏蔽 / 同一 ``(from,to)`` 重复上限 / 每回合 cap），再 argmax；掩码被清空时
   回退 ``EndTurn`` 并计 ``forced``。

动作索引 **原样透传**：竞技场 manifest 声明的 245 动作布局与 hsbg_engine 逐字节相同
（``action_layout_sha256 = be2e9758…e674bd``，含 196..244 的 49 个 ``Move { from, to }``），
所以本地选出的换位动作不需要任何转换。见 docs/POSITION_ACTION_AUDIT.md。

模型/映射路径可用环境变量覆盖：
``ARENA_MODEL``（默认 ``runs/az_entity_kl_30m/model_30m.pt``）、
``ARENA_CARD_MAP``（默认 ``runs/arena/card_map.json``；设为 ``off``/``native`` 表示
不做映射 —— 用本地引擎观测离线驱动 ``act`` 时必须这样，因为本地 cards 已经是 37.0
下标）、``ARENA_DEVICE``（默认 cuda:0）、
``ARENA_ACTION_LOG``（默认空=关闭；设为文件路径后每个决策追加一行 JSON：动作/动作段/
换位合法位数/累计计数 + 守卫触发情况，用于线上核验换位是否被选中、竞技场掩码是否给位）。

**换位去抖守卫（部署侧）默认开启**：``ARENA_MOVE_GUARD``（默认 ``1``）、
``ARENA_MOVE_CAP``（默认 3）、``ARENA_MOVE_REPEAT_LIMIT``（默认 2）。
不带守卫的部署路径实测每回合约 38 次换位（``runs/quality/s14_70M.json``：moves/turn
均值 6.81 / p90 38 / max 40，23.1% 的回合净盘面完全不变），这是纯空转、白耗每回合
40 个动作的上限。规则、开关、与训练守卫的一致性、局限见 **docs/ARENA_GUARD.md**。

注意：这是一次**零样本跨版本**评估——模型训练在 37.0.0 数据上，竞技场跑 36.6.3；
词表 id 对齐不代表数值/机制完全一致，结果里的失误应部分归因于此。
"""

from __future__ import annotations

import atexit
import json
import os
from typing import Any, Dict, Optional

import numpy as np

from hsbg.az.train.move_guard import (DEFAULT_MOVE_CAP, DEFAULT_MOVE_REPEAT_LIMIT,
                                      MoveGuard, is_move)
from hsbg.env.action_space_std import A_MOVE, N_BOARD, segment_of
from hsbg.env.obs_std import SLICE_CARD_BOARD, SLICE_CARD_HAND, SLICE_CARD_SHOP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS_FLOATS = 3227
OBS_CARDS = 124
N_ACTIONS = 245
MOVE_HI = A_MOVE + N_BOARD * N_BOARD  # 245

#: 守卫环境变量默认值（训练期一直开，部署侧跟随，见 docs/ARENA_GUARD.md）
GUARD_DEFAULT_ENABLED = True

_state: Dict[str, Any] = {
    "model": None, "torch": None, "device": None, "map": None, "ckpt": None,
    "norm_mean": None, "norm_std": None, "counters": None, "action_log": "",
    # ── 换位去抖守卫（默认开；关闭时这三项保持空 -> 旧行为逐位一致）──
    "guard": None, "guard_cfg": None, "turn_state": {},
}


# ══════════════════════════════════════════════════════════════════════
# 计数器 / 诊断
# ══════════════════════════════════════════════════════════════════════
def _counters() -> dict:
    """懒初始化并返回活计数器 dict（act 原地累加；测试直接塞 _state 也能用）。"""
    if _state.get("counters") is None:
        _state["counters"] = {"decisions": 0, "segments": {},
                              "move_legal_decisions": 0, "move_selected": 0,
                              "move_guard_blocked": 0, "move_guard_forced": 0,
                              "move_guard_moves": 0}
    return _state["counters"]


def _stats() -> dict:
    """本次进程的动作段计数快照（供 describe / 退出摘要）。"""
    return json.loads(json.dumps(_counters()))


# ══════════════════════════════════════════════════════════════════════
# 换位去抖守卫：配置 / 回合识别 / 状态
# ══════════════════════════════════════════════════════════════════════
def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return bool(default)
    return str(raw).strip().lower() not in ("0", "false", "no", "off", "none")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return int(default)
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return int(default)


def _guard_cfg() -> dict:
    """从环境变量读守卫配置（每次 act 都读，线上改了立刻生效）。"""
    cap = _env_int("ARENA_MOVE_CAP", DEFAULT_MOVE_CAP)
    repeat = _env_int("ARENA_MOVE_REPEAT_LIMIT", DEFAULT_MOVE_REPEAT_LIMIT)
    # 非法 / 越界值退回训练默认（守卫参数错了绝不能把对局搞崩）
    if cap < 0:
        cap = DEFAULT_MOVE_CAP
    if repeat < 1:
        repeat = DEFAULT_MOVE_REPEAT_LIMIT
    return {"enabled": _env_flag("ARENA_MOVE_GUARD", GUARD_DEFAULT_ENABLED),
            "cap": int(cap), "repeat_limit": int(repeat)}


def _guard() -> Optional[MoveGuard]:
    """当前配置的守卫（关闭时返回 ``None``：不建状态、不碰 mask）。

    配置变化（环境变量被改 / 测试切换）时重建对象并清空回合识别，保证
    ``ARENA_MOVE_GUARD=0`` 与旧路径逐位一致、``=1`` 时是干净状态。
    """
    cfg = _guard_cfg()
    if _state.get("guard_cfg") != cfg:
        _state["guard_cfg"] = cfg
        _state["guard"] = (MoveGuard(cap=cfg["cap"], repeat_limit=cfg["repeat_limit"])
                           if cfg["enabled"] else None)
        _state["turn_state"] = {}
    return _state.get("guard")


def guard_meta() -> dict:
    """守卫统计（关闭 -> ``{}``，键名与训练 ``move_guard_meta()`` 一致）。"""
    guard = _state.get("guard")
    return {} if guard is None else guard.to_meta()


def reset_state() -> None:
    """换一局 / 换 match 时清「回合识别 + 本回合换位历史」，累计统计保留。"""
    guard = _state.get("guard")
    if guard is not None:
        guard.clear_state()
    _state["turn_state"] = {}


def _ctx_int(context: Any, key: str) -> Optional[int]:
    """从竞技场 context 取整数字段；缺失 / 非法 -> ``None``。"""
    try:
        value = (context or {}).get(key)
    except AttributeError:          # context 不是 dict（老客户端）
        return None
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _match_key(context: Any) -> int:
    """match_id -> 整数键（字符串 id 用进程内 hash，保证同进程内稳定）。"""
    try:
        raw = (context or {}).get("match_id")
    except AttributeError:
        return 0
    if raw is None or raw == "":
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(hash(str(raw)) & 0x7FFFFFFF)


def _obs_signature(features: np.ndarray, cards: np.ndarray) -> tuple:
    """观测指纹：``(turn 标量, 棋盘/手牌/酒馆 卡牌多重集)``。

    换位只改棋盘**顺序**（多重集不变），买/卖/刷才会改多重集 —— 所以多重集在同一个
    回合内相对稳定，可作为「context 没有 turn 时」的新回合兜底信号。
    **宁可提前重置（漏挡一点）也不跨回合泄漏状态**。
    """
    turn_scalar = int(round(float(features[0]) * 20.0)) if features.size else -1

    def _bag(sl: slice) -> tuple:
        return tuple(sorted(int(v) for v in cards[sl]))

    return (turn_scalar, _bag(SLICE_CARD_BOARD), _bag(SLICE_CARD_HAND),
            _bag(SLICE_CARD_SHOP))


def _turn_entry(match_key: int, seat: int) -> dict:
    """``(match, seat)`` 的模块级回合状态（首次访问时创建）。

    字段与训练守卫同口径：``turn``（context.turn）、``last_action``、
    ``move_counts``（同一 ``(from,to)`` 次数）、``moves_this_turn``；
    另加 ``sig``（观测指纹）与 ``gen``（单调回合号，喂给 ``MoveGuard``）。
    """
    key = (int(match_key), int(seat))
    entry = _state["turn_state"].get(key)
    if entry is None:
        entry = {"turn": None, "sig": None, "gen": 0, "last_action": -1,
                 "move_counts": {}, "moves_this_turn": 0}
        _state["turn_state"][key] = entry
    return entry


def _turn_key(match_key: int, seat: int, context: Any,
              features: np.ndarray, cards: np.ndarray) -> int:
    """本决策所属回合的单调 key（同回合内稳定，换回合 +1）。

    判定优先级（无 reborn/replay 状态时的启发式，见 docs/ARENA_GUARD.md）：

    1. ``context["turn"]``（竞技场每步都给）变化 = 新回合；
    2. 之前没有 ``context.turn``、现在有了 = 保守视为新回合；
    3. 始终没有 ``context.turn`` → 退回观测指纹（turn 标量 + 卡牌多重集）变化 = 新回合。
    """
    ctx_turn = _ctx_int(context, "turn")
    sig = _obs_signature(features, cards)
    entry = _turn_entry(match_key, seat)
    if entry["sig"] is None and entry["turn"] is None:
        new_turn = False                        # 首次见到该 (match, seat)
    elif ctx_turn is not None and entry["turn"] is not None:
        new_turn = int(ctx_turn) != int(entry["turn"])
    elif ctx_turn is not None:
        new_turn = True
    else:
        new_turn = sig != entry["sig"]
    entry["turn"] = ctx_turn
    entry["sig"] = sig
    if new_turn:
        entry["gen"] = int(entry["gen"]) + 1
        entry["last_action"] = -1
        entry["move_counts"] = {}
        entry["moves_this_turn"] = 0
    return int(entry["gen"])


def _note_turn(match_key: int, seat: int, action: int) -> None:
    """记录本回合实际执行的动作（只用于诊断；规则判定在 MoveGuard 里）。"""
    entry = _state["turn_state"].get((int(match_key), int(seat)))
    if entry is None:
        return
    entry["last_action"] = int(action)
    if is_move(action):
        entry["moves_this_turn"] = int(entry["moves_this_turn"]) + 1
        counts = dict(entry["move_counts"])
        counts[int(action)] = counts.get(int(action), 0) + 1
        entry["move_counts"] = counts


# ══════════════════════════════════════════════════════════════════════
# 模型加载 / 观测准备
# ══════════════════════════════════════════════════════════════════════
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
    map_path = os.environ.get("ARENA_CARD_MAP",
                              os.path.join(ROOT, "runs/arena/card_map.json"))
    # ``off``/``native``：cards 已经是本仓库 37.0 下标（离线本地引擎观测），不再映射。
    if str(map_path).strip().lower() in ("off", "native", "identity", "0", "none"):
        mapping = None
        map_desc = "off(native)"
    else:
        with open(map_path, encoding="utf-8") as f:
            mapping = {int(k): int(v) for k, v in json.load(f)["mapping"].items()}
        map_desc = f"{len(mapping)} entries"
    cfg = _guard_cfg()
    _state.update({"model": model, "torch": torch, "device": dev,
                   "map": mapping, "ckpt": ckpt,
                   # 训练用 norm stats（多数 checkpoint 没有；有则必须一致，否则前向口径错）
                   "norm_mean": meta.get("norm_mean"),
                   "norm_std": meta.get("norm_std"),
                   "counters": {"decisions": 0, "segments": {},
                                "move_legal_decisions": 0, "move_selected": 0,
                                "move_guard_blocked": 0, "move_guard_forced": 0,
                                "move_guard_moves": 0},
                   "action_log": os.environ.get("ARENA_ACTION_LOG", "").strip(),
                   "guard_cfg": cfg,
                   "guard": (MoveGuard(cap=cfg["cap"], repeat_limit=cfg["repeat_limit"])
                             if cfg["enabled"] else None),
                   "turn_state": {}})
    guard_desc = ("on(cap=%d,repeat=%d)" % (cfg["cap"], cfg["repeat_limit"])
                  if cfg["enabled"] else "off")
    print(f"[arena-agent] model={ckpt} device={dev} arch={meta.get('arch')} "
          f"card_map={map_desc} "
          f"norm={'on' if _state['norm_mean'] is not None else 'off'} "
          f"move_guard={guard_desc} "
          f"action_log={_state['action_log'] or 'off'}", flush=True)
    if _state["action_log"]:
        atexit.register(_log_summary)


def _log_summary() -> None:
    """退出时把动作段计数 / 守卫统计打到 stdout（``--games N`` 跑完即可核对换位占比）。"""
    try:
        print("[arena-agent] action stats: " +
              json.dumps(_stats(), ensure_ascii=False, sort_keys=True), flush=True)
        meta = guard_meta()
        if meta:
            print("[arena-agent] move guard: " +
                  json.dumps(meta, ensure_ascii=False, sort_keys=True), flush=True)
    except Exception:  # noqa: BLE001 - 诊断输出绝不影响对局
        pass


def _prepare(observation):
    features = np.asarray(observation["features"], dtype=np.float32).reshape(-1)
    cards_raw = np.asarray(observation["cards"], dtype=np.int64).reshape(-1)
    mask = np.asarray(observation["action_mask"], dtype=bool).reshape(-1)
    if features.size < OBS_FLOATS or cards_raw.size < OBS_CARDS or mask.size != N_ACTIONS:
        raise ValueError(f"观测维度不符: features={features.size} cards={cards_raw.size} "
                         f"mask={mask.size}")
    mapping = _state.get("map")
    if mapping:
        cards = np.array([mapping.get(int(v), 0) for v in cards_raw[:OBS_CARDS]],
                         dtype=np.int64)
    else:
        cards = cards_raw[:OBS_CARDS].astype(np.int64, copy=True)
    x = features[:OBS_FLOATS]
    if _state.get("norm_mean") is not None:
        x = x - _state["norm_mean"]
    if _state.get("norm_std") is not None:
        x = x / _state["norm_std"]
    return np.ascontiguousarray(x, dtype=np.float32), cards, np.ascontiguousarray(mask)


# ══════════════════════════════════════════════════════════════════════
# 竞技场回调
# ══════════════════════════════════════════════════════════════════════
def act(observation, context):  # noqa: ANN001 - 竞技场回调签名
    """返回 0..244 的合法动作（守卫改写 mask 后 masked argmax，无搜索）。

    换位（196..244）与其它动作同权：掩码里给位就参与 argmax，返回的就是**同一个索引**
    （竞技场动作布局与本地逐字节一致，无需映射）。

    守卫（默认开，``ARENA_MOVE_GUARD=0`` 关闭）在 argmax 之前把「逆换位 / 重复超限 /
    本回合超 cap」的换位位清 0；清空后只剩 EndTurn 则返回 0 并计 ``forced``。
    本函数是**有状态**的：按 ``(match_id, seat)`` 维护「本回合」动作历史，
    ``context["turn"]`` 变化即重置。``ARENA_ACTION_LOG`` 打开时逐决策落盘（含守卫触发）。
    """
    _load()
    torch = _state["torch"]
    from hsbg.az.train.ppo import (forward_model, split_model_outputs)

    features, cards, mask = _prepare(observation)
    if not mask.any():
        return 0
    dev = torch.device(_state["device"])
    match_key = _match_key(context)
    seat_raw = _ctx_int(context, "seat")
    seat = 0 if seat_raw is None else int(seat_raw)
    # 环境给的原始掩码口径（诊断/日志用；守卫只是在这上面再清位）
    raw_mask_legal = int(mask.sum())
    raw_move_legal = int(mask[A_MOVE:MOVE_HI].sum())

    # ── 换位去抖守卫：argmax 之前改写 mask（规则与训练共用 MoveGuard）──
    guard = _guard()
    turn_key = None
    guard_forced = False
    guard_blocked = 0
    if guard is not None:
        turn_key = _turn_key(match_key, seat, context, features, cards)
        mask, guard_forced = guard.guarded_mask(mask, game_id=match_key,
                                                seat=seat, turn=turn_key)
        guard_blocked = max(0, raw_mask_legal - int(mask.sum()))

    x = torch.from_numpy(features.reshape(1, -1)).to(dev)
    c = torch.from_numpy(cards.reshape(1, -1)).to(dev)
    m = torch.from_numpy(np.ascontiguousarray(mask).reshape(1, -1)).to(dev)
    with torch.no_grad():
        logits, _rank_logits, _scalar = split_model_outputs(
            forward_model(_state["model"], x, c, m))
        logits = logits[0, :N_ACTIONS].masked_fill(~m[0], -float("inf"))
        action = int(torch.argmax(logits).item())
    action = int(action) if mask[action] else int(np.flatnonzero(mask)[0])

    # 守卫只统计**实际执行**的动作：EndTurn/其它动作只更新「上一步」，
    # Move 才进本回合换位历史（供下一决策算逆换位/重复/cap）。
    if guard is not None:
        guard.note_action(action, game_id=match_key, seat=seat, turn=turn_key)
        _note_turn(match_key, seat, action)

    # ── 诊断（默认零影响：只在 ARENA_ACTION_LOG 非空时写）──
    seg = segment_of(action)
    stats = _counters()
    stats["decisions"] += 1
    stats["segments"][seg] = int(stats["segments"].get(seg, 0)) + 1
    move_legal = int(raw_move_legal)
    if move_legal > 0:
        stats["move_legal_decisions"] += 1
    if seg == "move":
        stats["move_selected"] += 1
    if guard is not None:
        stats["move_guard_blocked"] = int(stats["move_guard_blocked"]) + int(guard_blocked)
        if guard_forced:
            stats["move_guard_forced"] = int(stats["move_guard_forced"]) + 1
        if is_move(action):
            stats["move_guard_moves"] = int(stats["move_guard_moves"]) + 1
    if _state.get("action_log"):
        ctx = context or {}
        rec = {"match_id": ctx.get("match_id"), "seat": ctx.get("seat"),
               "turn": ctx.get("turn"), "actions_used": ctx.get("actions_used"),
               "action": action, "segment": seg,
               "mask_legal": int(raw_mask_legal),
               "move_legal_bits": move_legal,
               "counter": stats["decisions"]}
        if guard is not None:
            entry = _state["turn_state"].get((int(match_key), int(seat))) or {}
            rec.update({"move_guard": True,
                        "guard_forced": bool(guard_forced),
                        "guard_blocked": int(guard_blocked),
                        "move_cap": int(guard.cap),
                        "move_repeat_limit": int(guard.repeat_limit),
                        "moves_this_turn": int(entry.get("moves_this_turn", 0)),
                        "turn_key": int(turn_key)})
        try:
            with open(_state["action_log"], "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return action


def describe() -> dict:
    guard = _state.get("guard")
    out = {"checkpoint": _state.get("ckpt"),
           "device": _state.get("device"),
           "card_map_entries": len(_state.get("map") or {}),
           "card_map": "off(native)" if not _state.get("map") else "arena 36.6 -> 37.0",
           "norm_stats": _state.get("norm_mean") is not None,
           "action_log": _state.get("action_log") or None,
           "stats": _stats() if _state.get("counters") else None}
    if guard is None:
        out["move_guard"] = {"enabled": False}
    else:
        meta = guard.to_meta()
        meta["enabled"] = True
        meta["seats_tracked"] = len(_state.get("turn_state") or {})
        out["move_guard"] = meta
    return out
