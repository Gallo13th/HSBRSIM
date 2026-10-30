#!/usr/bin/env python3
"""换位动作（Move / reposition，索引 196..244）全链路探针。

一次性回答四个问题（对应 docs/POSITION_ACTION_AUDIT.md）：

1. ``engine``  ：引擎是否把 196..244 置位、``step`` 是否接受换位、棋盘顺序是否真的变；
2. ``collect`` ：训练采集（``PPOSelfPlayPolicy`` 采样）里换位被采样到多少次 / 有多少次可换位；
3. ``eval``    ：训练出的 checkpoint 在 greedy 评测里实际选了多少次换位（默认 64 局）；
4. ``arena``   ：``scripts/arena_agent.act`` 输出的索引在 0..244 的动作布局里落在哪一段
   （验证有没有在适配层被丢弃/改写）。

用法::

    PYTHONPATH=rust/python:. python scripts/probe_reposition.py --mode engine
    PYTHONPATH=rust/python:. python scripts/probe_reposition.py --mode collect \
        --checkpoint runs/az_entity_s8b/model.pt --games 16 --device cuda:7
    PYTHONPATH=rust/python:. python scripts/probe_reposition.py --mode eval \
        --checkpoint runs/az_entity_s8b/snapshots/xxx.pt --games 64 --device cuda:7
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.env import action_space_std as A  # noqa: E402

MOVE_LO, MOVE_HI = A.A_MOVE, A.A_MOVE + A.N_BOARD * A.N_BOARD  # 196..245


def _mask(game: Any, seat: int) -> np.ndarray:
    return np.frombuffer(game.legal_mask(int(seat)), dtype=np.uint8).astype(bool)


def _board(game: Any, seat: int) -> List[Dict[str, Any]]:
    pj = json.loads(game.player_json(int(seat)))
    return list(pj.get("board") or [])


def _board_sig(board: List[Dict[str, Any]]) -> List[str]:
    return [str(m.get("card")) for m in board]


def _drive_to_turn(game: Any, seat: int, target_turn: int, max_steps: int = 20000) -> int:
    """让 ``seat`` 用引擎脚本 bot 决策、其余座位 ``bot_play``，推进到 ``target_turn``。"""
    steps = 0
    while not game.is_over() and int(game.turn) < target_turn and steps < max_steps:
        acted = False
        for p in range(int(game.num_players)):
            if game.is_over() or int(game.turn) >= target_turn:
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == int(seat):
                game.step(p, int(game.bot_action(p)))
            else:
                game.bot_play(p)
        if not acted:
            break
    return int(game.turn)


def _settle_seat(game: Any, seat: int, max_steps: int = 64) -> int:
    """把 learner 座位从 pending choice（Discover/ChooseOne/Target）推进到常规招募阶段。

    pending 态下 ``legal_mask`` 只置位 Choose/Cancel（见 actions.rs:220-226），换位段必然全 0；
    探针必须先解掉 pending 才能测换位。返回实际步数。
    """
    acted = 0
    for _ in range(max_steps):
        if game.is_over() or not game.needs_action(seat):
            break
        mask = _mask(game, seat)
        if mask[MOVE_LO:MOVE_HI].any():
            break
        choose = np.flatnonzero(mask[A.A_CHOOSE:A.A_CHOOSE + A.N_CHOICE])
        if mask[A.A_CANCEL] and not choose.size:
            game.step(seat, A.A_CANCEL)
            acted += 1
            continue
        if not choose.size:
            break
        game.step(seat, int(A.A_CHOOSE + choose[0]))
        acted += 1
    return acted


def mode_engine(args: argparse.Namespace) -> Dict[str, Any]:
    import hsbg_engine as E

    out: Dict[str, Any] = {
        "action_space": {
            "A_MOVE": A.A_MOVE,
            "move_segment": [MOVE_LO, MOVE_HI - 1],
            "move_count": MOVE_HI - MOVE_LO,
            "encode_example": {"Move(src=0,to=1)": A.encode(A.Move(src=0, to=1)),
                               "Move(src=6,to=0)": A.encode(A.Move(src=6, to=0))},
        }
    }

    game = E.Game(seed=int(args.seed))
    turn = _drive_to_turn(game, 0, int(args.turn))
    settled = _settle_seat(game, 0)
    board = _board(game, 0)
    if len(board) < 2:
        # 兜底：用 inject_board 精确摆一个 ≥2 随从的棋盘（不改其它字段）
        base = board[0] if board else {"card": 1}
        card = int(base.get("card") or 1)
        rep = game.inject_board(0, [[card, 2, 2], [card, 3, 3], [card, 1, 1]], 4)
        out["injected_board"] = rep.get("applied")
        out["injected_board_reason"] = rep.get("reason")
        turn = int(game.turn)
        board = _board(game, 0)

    mask = _mask(game, 0)
    legal_all = int(mask.sum())
    legal_move = int(mask[MOVE_LO:MOVE_HI].sum())
    rel = np.flatnonzero(mask[MOVE_LO:MOVE_HI])
    move_pairs = [(int(i) // A.N_BOARD, int(i) % A.N_BOARD) for i in rel]
    out.update({
        "turn": turn,
        "board_len": len(board),
        "board_sig_before": _board_sig(board),
        "mask_legal_total": legal_all,
        "mask_move_legal": legal_move,
        "mask_move_true_bits": [int(i) for i in np.flatnonzero(mask) if MOVE_LO <= i < MOVE_HI],
        "move_pairs": move_pairs,
        "mask_identity_move_legal": [bool(mask[A.encode(A.Move(src=k, to=k))]) for k in range(7)],
    })

    # step 接受性 + board 顺序变化
    if move_pairs:
        src, dst = move_pairs[0]
        before = _board_sig(_board(game, 0))
        idx = A.encode(A.Move(src=src, to=dst))
        try:
            game.step(0, idx)
            after = _board_sig(_board(game, 0))
            out["step_accepted"] = True
            out["step_action"] = {"index": idx, "src": src, "to": dst}
            out["board_sig_after"] = after
            out["board_order_changed"] = bool(before != after)
            out["step_error"] = None
        except Exception as exc:  # noqa: BLE001
            out["step_accepted"] = False
            out["step_action"] = {"index": idx, "src": src, "to": dst}
            out["board_sig_after"] = _board_sig(_board(game, 0))
            out["board_order_changed"] = False
            out["step_error"] = f"{type(exc).__name__}: {exc}"
    else:
        out["step_accepted"] = None
        out["step_error"] = "no legal move in mask"

    # 非法换位必须被拒绝（from==to）
    idx_same = A.encode(A.Move(src=0, to=0))
    try:
        game.step(0, idx_same)
        out["identity_move_accepted"] = True
    except Exception as exc:  # noqa: BLE001
        out["identity_move_accepted"] = False
        out["identity_move_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _count_moves(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(records)
    acts = np.asarray([int(r["action"]) for r in records], dtype=np.int64)
    masks = np.stack([np.asarray(r["mask"], dtype=bool) for r in records]) if n else None
    stat: Dict[str, Any] = {
        "decisions": n,
        "move_selected": int(((acts >= MOVE_LO) & (acts < MOVE_HI)).sum()),
        "move_selected_share": float(((acts >= MOVE_LO) & (acts < MOVE_HI)).mean()) if n else 0.0,
        "decisions_with_move_legal": int(masks[:, MOVE_LO:MOVE_HI].any(axis=1).sum()) if n else 0,
        "move_legal_bits_total": int(masks[:, MOVE_LO:MOVE_HI].sum()) if n else 0,
        "forced": int(sum(bool(r.get("forced")) for r in records)),
        "end_turn": int((acts == 0).sum()),
        "action_hist": {},
    }
    # 动作段直方图（用 action_space_std 的 SEGMENTS）
    for name, lo, hi, _c, _d in A.SEGMENTS:
        k = int(((acts >= lo) & (acts < min(hi, A.N_ACTIONS))).sum())
        if k:
            stat["action_hist"][name] = k
    return stat


def mode_collect(args: argparse.Namespace) -> Dict[str, Any]:
    """采集一批自对弈记录（PPOSelfPlayPolicy 真实采样路径），统计换位采样次数。"""
    import torch
    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.parallel_collect import collect_ppo_records_parallel
    from hsbg.az.train.ppo import CollectConfig

    dev = args.device
    model, meta = load_checkpoint(args.checkpoint, device=dev)
    model.eval()
    cfg = CollectConfig(games=int(args.games), seed=int(args.seed),
                        opponent=str(args.opponent), behavior="net",
                        temperature=float(args.temperature))
    records, cmeta = collect_ppo_records_parallel(
        model, cfg, device=dev, workers=min(int(args.workers), int(args.games)),
        search_fn=None, search_config=None, eval_fn=None, seed=int(args.seed))
    stat = _count_moves(records)
    stat["checkpoint"] = args.checkpoint
    stat["arch"] = meta.get("arch")
    stat["collect_meta"] = {k: cmeta.get(k) for k in
                            ("mode", "games", "decisions", "illegal_actions",
                             "truncated_games", "forced_end_turns", "records")}
    return stat


def mode_eval(args: argparse.Namespace) -> Dict[str, Any]:
    """64 局 greedy 评测：learner 实际动作分布（换位选中次数/占比）。

    复用官方评测口径 ``hsbg.az.train.evaluate.evaluate_policy``（seat0 = learner，
    其余 7 座 = 引擎 bot，固定 seed），只在 ``PPOGreedyPolicy.decide`` 外挂一个记录器，
    所以统计到的动作就是**训练同一策略头 + masked argmax** 的真实输出。
    """
    from hsbg.az.train.evaluate import EvalConfig, evaluate_policy
    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.ppo import PPOEvaluator, PPOGreedyPolicy

    dev = args.device
    model, meta = load_checkpoint(args.checkpoint, device=dev)
    model.eval()
    ev = PPOEvaluator(model, device=dev,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))

    records: List[Dict[str, Any]] = []

    class _RecordingGreedy(PPOGreedyPolicy):
        def decide(self, game: Any, seat: int):
            dec = super().decide(game, seat)
            records.append({"action": int(dec.action),
                            "mask": _mask(game, seat),
                            "forced": bool((dec.info or {}).get("forced"))})
            return dec

    policy = _RecordingGreedy(ev, max_actions_per_turn=40)
    res = evaluate_policy(policy, EvalConfig(games=int(args.games),
                                            seed=int(args.seed),
                                            max_steps=int(args.max_steps),
                                            policy_seat=0))
    stat = _count_moves(records)
    stat.update({
        "checkpoint": args.checkpoint,
        "arch": meta.get("arch"),
        "games": res.get("games"),
        "games_finished": res.get("games_finished"),
        "mean_rank": res.get("mean_rank"),
        "top4_rate": res.get("top4_rate"),
        "win_rate": res.get("win_rate"),
        "legal_action_rate": res.get("legal_action_rate"),
        "truncated_games": res.get("truncated_games"),
        "eval_decisions": res.get("decisions"),
    })
    return stat


def mode_trace(args: argparse.Namespace) -> Dict[str, Any]:
    """逐动作追踪 seat0：换位动作是否被引擎接受、棋盘顺序是否真的改变。

    驱动循环与 ``hsbg.az.train.evaluate.evaluate_policy`` 相同（seat0 = learner，
    其余 7 座 ``bot_play``，``policy.reset()`` 每局一次），只在换位动作前后各取一次
    棋盘卡牌序列，所以能区分「真实改变顺序」和「换了顺序上不可见的同卡随从」，
    并统计同一回合内立即反向（undo）的换位次数。
    """
    import hsbg_engine as E
    from hsbg.az.train.common import mask_from_bytes
    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.ppo import PPOEvaluator, PPOGreedyPolicy

    dev = args.device
    model, meta = load_checkpoint(args.checkpoint, device=dev)
    model.eval()
    ev = PPOEvaluator(model, device=dev,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    policy = PPOGreedyPolicy(ev, max_actions_per_turn=40)
    traces: List[Dict[str, Any]] = []
    errors: List[str] = []
    decisions = 0
    for gi in range(int(args.games)):
        game = E.Game(seed=int(args.seed) + gi)
        policy.reset()
        steps = 0
        while not game.is_over() and steps < int(args.max_steps):
            acted = False
            for p in range(int(game.num_players)):
                if not game.needs_action(p):
                    continue
                acted = True
                steps += 1
                if p != 0:
                    game.bot_play(p)
                    continue
                mask = mask_from_bytes(game.legal_mask(0))
                dec = policy.decide(game, 0)
                a = int(dec.action)
                if not (0 <= a < mask.size and bool(mask[a])):
                    a = int(np.flatnonzero(mask)[0]) if mask.any() else 0
                decisions += 1
                if MOVE_LO <= a < MOVE_HI:
                    before = _board_sig(_board(game, 0))
                    try:
                        game.step(0, a)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"game{gi} turn{int(game.turn)} a={a}: "
                                      f"{type(exc).__name__}: {exc}")
                        continue
                    after = _board_sig(_board(game, 0))
                    traces.append({"game": gi, "turn": int(game.turn), "action": a,
                                   "src": (a - MOVE_LO) // A.N_BOARD,
                                   "dst": (a - MOVE_LO) % A.N_BOARD,
                                   "before": before, "after": after,
                                   "changed": bool(before != after)})
                else:
                    try:
                        game.step(0, a)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"game{gi} turn{int(game.turn)} a={a}: "
                                      f"{type(exc).__name__}: {exc}")
                if game.is_over():
                    break
            if not acted:
                break

    n = len(traces)
    undone = 0
    repeat_same = 0
    per_turn: Dict[tuple, int] = {}
    per_turn_actions: Dict[tuple, set] = {}
    prev: Dict[str, Any] = {}
    for t in traces:
        key = (int(t["game"]), int(t["turn"]))
        per_turn[key] = per_turn.get(key, 0) + 1
        per_turn_actions.setdefault(key, set()).add(int(t["action"]))
        pv = prev.get(f"{t['game']}")
        if pv is not None and int(pv["turn"]) == int(t["turn"]):
            if int(pv["dst"]) == int(t["src"]) and int(pv["src"]) == int(t["dst"]):
                undone += 1
            if int(pv["action"]) == int(t["action"]):
                repeat_same += 1
        prev[f"{t['game']}"] = t
    seen_before = {}
    for t in traces:
        seen_before.setdefault((int(t["game"]), int(t["turn"])), t["before"])
    net_unchanged_turns = 0
    last_after = {}
    for t in traces:
        last_after[(int(t["game"]), int(t["turn"]))] = t["after"]
    for key, b in seen_before.items():
        if last_after.get(key) == b:
            net_unchanged_turns += 1
    return {
        "checkpoint": args.checkpoint,
        "arch": meta.get("arch"),
        "games": int(args.games),
        "decisions": decisions,
        "move_selected": n,
        "move_step_ok": n - len(errors),
        "step_errors": errors[:5],
        "move_board_order_changed": int(sum(1 for t in traces if t["changed"])),
        "move_board_order_unchanged_same_card_ids": int(sum(1 for t in traces if not t["changed"])),
        "immediate_undo_pairs": undone,
        "repeat_same_move_back_to_back": repeat_same,
        "turns_with_move": len(per_turn),
        "moves_per_turn_max": max(per_turn.values()) if per_turn else 0,
        "moves_per_turn_mean": float(np.mean(list(per_turn.values()))) if per_turn else 0.0,
        "distinct_move_actions_per_turn_mean": (
            float(np.mean([len(v) for v in per_turn_actions.values()]))
            if per_turn_actions else 0.0),
        "turns_net_board_unchanged": net_unchanged_turns,
        "examples": traces[:5],
    }


def mode_head(args: argparse.Namespace) -> Dict[str, Any]:
    """诊断 Move 段 logits 的结构：状态相关部分对 (from,to) **对称**。

    entity 模型 ``logits[196:245] = pointer_scale * (hb_i · hb_j) + move_bias[i,j]``，
    而 ``hb_i · hb_j`` 本身对 i↔j 完全对称 —— 因此 ``Move{i→j}`` 与 ``Move{j→i}`` 的
    logit 差只等于 ``move_bias`` 的反对称部分。这里在真实局面上量化该差值。
    """
    import hsbg_engine as E
    import torch
    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.ppo import forward_model, split_model_outputs

    dev = args.device
    model, meta = load_checkpoint(args.checkpoint, device=dev)
    model.eval()
    game = E.Game(seed=int(args.seed))
    turn = _drive_to_turn(game, 0, int(args.turn))
    settled = _settle_seat(game, 0)
    game.inject_board(0, [[1, 2, 2], [2, 3, 3], [3, 1, 1], [4, 4, 4]], 4)
    raw = game.observe(0)
    f = np.frombuffer(raw[0], dtype=np.float32).copy()
    c = np.frombuffer(raw[1], dtype=np.int32).copy()
    mask = _mask(game, 0)
    x = torch.from_numpy(f.reshape(1, -1)).to(dev)
    cc = torch.from_numpy(c.reshape(1, -1)).to(dev)
    m = torch.from_numpy(mask.reshape(1, -1)).to(dev)
    with torch.no_grad():
        logits, _rl, _sc = split_model_outputs(forward_model(model, x, cc, m))
    L = logits[0, MOVE_LO:MOVE_HI].reshape(A.N_BOARD, A.N_BOARD).detach().cpu() \
        .numpy().astype(np.float64)
    bias = model.move_bias.detach().cpu().numpy().astype(np.float64)
    n = len(_board(game, 0))
    pairs = [(i, j) for i in range(n) for j in range(n) if i != j]
    asym = [L[i, j] - L[j, i] for i, j in pairs]
    sym = [(L[i, j] + L[j, i]) / 2.0 for i, j in pairs]
    bias_asym = [bias[i, j] - bias[j, i] for i, j in pairs]
    full = logits[0, :A.N_ACTIONS].detach().cpu().numpy().astype(np.float64)
    legal = np.flatnonzero(mask)
    nonmove = [int(a) for a in legal if not (MOVE_LO <= int(a) < MOVE_HI)]
    best_move = float(max(L[i, j] for i, j in pairs)) if pairs else float("nan")
    best_nonmove = float(max(full[a] for a in nonmove)) if nonmove else float("nan")
    return {
        "checkpoint": args.checkpoint,
        "arch": meta.get("arch"),
        "turn": int(turn),
        "settle_steps": int(settled),
        "board_len": n,
        "board": _board_sig(_board(game, 0)),
        "best_move_logit": best_move,
        "best_nonmove_legal_logit": best_nonmove,
        "move_margin_best_nonmove_minus_best_move": (
            best_nonmove - best_move if nonmove and pairs else None),
        "n_legal": int(legal.size),
        "move_logits": {f"{i}->{j}": float(L[i, j]) for i, j in pairs},
        "logit_spread_across_pairs": float(np.max(sym) - np.min(sym)),
        "direction_delta_max": float(np.max(np.abs(asym))),
        "direction_delta_mean_abs": float(np.mean(np.abs(asym))),
        "move_bias_direction_delta_max": float(np.max(np.abs(bias_asym))),
        "move_bias_offdiag_mean": float(np.mean(bias[~np.eye(A.N_BOARD, dtype=bool)])),
        "note": ("direction_delta ≈ move_bias 反对称部分：状态相关项 hb_i·hb_j 对 i↔j 对称，"
                 "模型无法从棋盘状态学习「往哪个方向挪」"),
    }


def mode_arena(args: argparse.Namespace) -> Dict[str, Any]:
    """验证 arena 适配层：动作布局哈希一致 + act() 原样透传换位索引。

    - 布局：本地 245 个动作名序列的 sha256 必须等于竞技场公开 manifest 的
      ``action_layout_sha256``（196..244 = 49 个 ``Move { from, to }``）；
    - 透传：把 ``ARENA_MODEL`` 指到给定 checkpoint，构造一个**只有换位合法**的合成观测，
      ``arena_agent.act`` 必须返回那个换位索引（而不是回退成 EndTurn/丢弃）。
    """
    import hashlib

    import scripts.arena_agent as AA
    import hsbg_engine as E

    ours = [E.action_name(i) for i in range(A.N_ACTIONS)]
    canonical = json.dumps(ours, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()
    out: Dict[str, Any] = {
        "arena_agent_maps": "identity（返回同一个 0..244 索引，不做重编码）",
        "move_range": [MOVE_LO, MOVE_HI - 1],
        "move_names_196_198": ours[MOVE_LO:MOVE_LO + 3],
        "move_name_244": ours[MOVE_HI - 1],
        "local_action_layout_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    manifest_path = args.manifest or "/tmp/arena_manifest.json"
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            mani = json.load(f)
        arena = list(mani.get("actions") or [])
        diffs = [i for i, (a, b) in enumerate(zip(ours, arena)) if a != b]
        out["manifest"] = {
            "path": manifest_path,
            "ruleset_id": mani.get("ruleset_id"),
            "protocol_version": mani.get("protocol_version"),
            "environment": mani.get("environment", {}).get("version"),
            "n_actions": len(arena),
            "action_layout_sha256": mani.get("action_layout_sha256"),
            "sha256_match": hashlib.sha256(canonical).hexdigest()
                             == mani.get("action_layout_sha256"),
            "name_diffs": diffs[:10],
            "n_name_diffs": len(diffs),
            "arena_move_197": arena[197] if len(arena) > 197 else None,
            "arena_move_244": arena[244] if len(arena) > 244 else None,
        }
    else:
        out["manifest"] = {"path": manifest_path, "found": False}

    # act() 原样透传：只给一个换位位
    if args.checkpoint and os.path.isfile(args.checkpoint):
        target = A.encode(A.Move(src=1, to=0))  # 203
        mask = np.zeros(A.N_ACTIONS, dtype=np.uint8)
        mask[target] = 1
        obs = {"features": np.zeros(3227, dtype=np.float32),
               "cards": np.zeros(124, dtype=np.int64),
               "action_mask": mask}
        os.environ["ARENA_MODEL"] = os.path.abspath(args.checkpoint)
        os.environ["ARENA_DEVICE"] = args.device
        got = int(AA.act(obs, {"match_id": "<probe>", "seat": 0, "turn": 0}))
        out["act"] = {"checkpoint": args.checkpoint,
                      "only_legal_action": target,
                      "returned": got,
                      "unchanged": bool(got == target),
                      "in_move_segment": bool(MOVE_LO <= got < MOVE_HI)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode",
                    choices=("engine", "collect", "eval", "trace", "head", "arena", "all"),
                    default="engine")
    ap.add_argument("--checkpoint", default="runs/az_entity_s8b/model.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--turn", type=int, default=6)
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--opponent", default="bot")
    ap.add_argument("--manifest", default="", help="TavernArena /api/v1/manifest JSON（arena 模式）")
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    fns = {"engine": mode_engine, "collect": mode_collect,
           "eval": mode_eval, "trace": mode_trace, "head": mode_head,
           "arena": mode_arena}
    modes = list(fns) if args.mode == "all" else [args.mode]
    res: Dict[str, Any] = {}
    for m in modes:
        res[m] = fns[m](args)
        print(f"== {m} ==", flush=True)
        print(json.dumps(res[m], ensure_ascii=False, indent=2, default=str), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
