#!/usr/bin/env python3
"""对局质量监控：逐回合记录我方战团强度/经济，并与真实 10k+ MMR 同 turn 分位对比。

指标（learner seat）：
- board_strength = Σ(atk+hp)，board_count，tier，gold，health，turn
- 死亡回合、死亡时战团强度、每 turn 的强度分位
对比基准：data/real_library/strength_calibration.json 的 real p50/p75/p90（分 turn）。

用法::

  PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
    --checkpoint runs/champion_c0_1746.pt --device cuda:2 --games 256 \
    --seed-base 520000 --out runs/quality/champ_1746.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, mask_from_bytes  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402


def _board_stats(pj: dict) -> dict:
    board = pj.get("board") or []
    strength = 0
    for m in board:
        strength += int(m.get("atk") or 0) + int(m.get("hp") or 0)
    return {"strength": strength, "count": len(board)}


def _board_sig(game, seat: int = 0) -> list[str]:
    """棋盘卡牌序列（**顺序敏感**）：换位的净效果就看这个签名是否变化。"""
    pj = json.loads(game.player_json(int(seat)))
    return [str(m.get("card")) for m in (pj.get("board") or [])]


def _carrier_panel(rows: list, carrier_ids) -> dict:
    """质量面板的载体三指标（docs/CARRIER_SCALING.md §4）。

    - ``carrier_encounter_rate``：局级载体率（曾有主集合载体上场）；
    - ``casts_on_carrier_mean``：每局「目标选择命中载体」的施法次数；
    - ``r_carrier_turns_str12``：r(载体在场回合数 ≤12, Σ₁₂)（Pearson + bootstrap CI）。

    注：本面板只走「目标选择」口径（不解析引擎日志），所以是**严格下界**；
    完整的「触发载体施法」口径见 ``scripts/carrier_audit.py`` / ``carrier_metrics.py``。
    """
    carrier_ids = set(carrier_ids or [])
    if not carrier_ids:
        return {"carrier_audit": False}
    ok = [r for r in rows if r and r.get("turns")]

    def _ct12(r):
        return sum(1 for t in r["turns"]
                   if int(t.get("turn") or 0) <= 12 and t.get("board_carriers"))

    def _s12(r):
        for t in r["turns"]:
            if int(t.get("turn") or 0) == 12:
                return int(t.get("strength") or 0)
        return None

    ever = [r for r in ok if any(t.get("board_carriers") for t in r["turns"])]
    t9 = [r for r in ok if any(int(t.get("turn") or 0) == 9 and t.get("board_carriers")
                               for t in r["turns"])]
    t12 = [r for r in ok if any(int(t.get("turn") or 0) == 12 and t.get("board_carriers")
                                for t in r["turns"])]
    shop = [r for r in ok if r.get("carrier_shop_seen")]
    casts = [int(r.get("casts_on_carrier") or 0) for r in ok]
    corr_rows = [r for r in ok if _s12(r) is not None]
    ct = [_ct12(r) for r in corr_rows]
    sv = [_s12(r) for r in corr_rows]
    r_p = r_s = None
    ci = None
    try:
        from scripts.carrier_common import _boot_corr_ci, _pearson, _spearman
        r_p = _pearson(ct, sv)
        r_s = _spearman(ct, sv)
        ci = _boot_corr_ci(ct, sv)
    except BaseException:  # noqa: BLE001
        pass
    return {
        "carrier_audit": True,
        "carrier_ids": len(carrier_ids),
        "carrier_encounter_rate": (len(ever) / len(ok)) if ok else None,
        "carrier_t9_rate": (len(t9) / len(ok)) if ok else None,
        "carrier_t12_rate": (len(t12) / len(ok)) if ok else None,
        "carrier_shop_offer_rate": (len(shop) / len(ok)) if ok else None,
        "carrier_turns_mean": (sum(ct) / len(ct)) if ct else 0.0,
        "casts_on_carrier_mean": (sum(casts) / len(casts)) if casts else 0.0,
        "casts_on_carrier_mean_given_carrier": (
            sum(int(r.get("casts_on_carrier") or 0) for r in ever) / len(ever)
            if ever else 0.0),
        "r_carrier_turns_str12": r_p,
        "r_carrier_turns_str12_ci95": ci,
        "r_carrier_turns_str12_spearman": r_s,
        "n_t12": len(corr_rows),
        "str12_p50": (float(np.percentile(sv, 50)) if sv else None),
    }


def _play(seed: int, policy, q: dict) -> dict | None:
    """跑一局；返回 {'placement','death_turn','death_strength','turns':[{...}]}。

    每个 turn 行额外记录 ``moves``（本回合 learner 选择的换位次数）、
    ``board_start``/``board_end``（回合内 learner **最后一次行动后**的棋盘卡牌序列），
    用于统计「每回合换位次数」与「净盘面不变回合比例」。
    """
    import hsbg_engine as E

    game = E.Game(seed=int(seed))
    policy.reset()
    turns = []
    last_turn = -1
    steps = 0
    max_steps = int((q or {}).get("max_steps", 20000) or 20000)
    # ── 载体审计（docs/CARRIER_SCALING.md）：局级载体率 + 对载体施法 ──
    carrier_ids = set((q or {}).get("carrier_ids") or [])
    cid2id = dict((q or {}).get("cid2id") or {})
    casts_on_carrier = 0
    carrier_shop_seen = False
    carrier_turns = 0
    # 与 official eval（hsbg/az/train/evaluate.py）一致：**每个 pass 每个座位只走一步**。
    # 不能用 `while needs_action(p)`：引擎可能在一次 EndTurn 后立刻推进到下一回合，
    # 会把两个回合的 learner 动作记进同一行（历史 quality_monitor 的 turn 行会错位）。
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pj = json.loads(game.player_json(0))
            bs = _board_stats(pj)
            board_ids = [cid2id.get(int(m.get("card")), "")
                         for m in (pj.get("board") or [])]
            board_carriers = [x for x in board_ids if x in carrier_ids]
            shop_carriers = []
            for slot in (pj.get("shop") or []):
                item = (slot or {}).get("item") if isinstance(slot, dict) else None
                m = item.get("Minion") if isinstance(item, dict) else None
                if isinstance(m, dict):
                    cid = cid2id.get(int(m.get("card")), "")
                    if cid in carrier_ids:
                        shop_carriers.append(cid)
            if shop_carriers:
                carrier_shop_seen = True
            if board_carriers:
                carrier_turns += 1
            turns.append({"turn": t, "strength": bs["strength"], "count": bs["count"],
                          "tier": int(pj.get("tier") or 0), "gold": int(pj.get("gold") or 0),
                          "health": int(pj.get("health") or 0),
                          "alive": bool(pj.get("alive", True)),
                          "moves": 0, "move_legal": False,
                          "board_carriers": board_carriers,
                          "shop_carrier_ids": shop_carriers,
                          "casts_on_carrier_turn": 0,
                          "board_start": [str(m.get("card")) for m in (pj.get("board") or [])],
                          "board_end": None})
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == 0:
                m = mask_from_bytes(game.legal_mask(0))
                if bool(m[196:245].any()):
                    turns[-1]["move_legal"] = True
                # 待选目标（施法打谁）：只有出现选择时才多取一次 view（约 0.17ms）
                pend_opts = None
                pend_carrier_eids = set()
                if carrier_ids and bool(m[30:46].any()):
                    try:
                        view = json.loads(game.view(0))
                        me_v = view.get("me") or {}
                        pend = me_v.get("pending") or {}
                        if str(pend.get("kind")) == "target":
                            pend_opts = list(pend.get("options") or [])
                            pend_carrier_eids = {
                                int(x.get("eid")) for x in (me_v.get("board") or [])
                                if str(x.get("id")) in carrier_ids}
                    except BaseException:  # noqa: BLE001
                        pend_opts = None
                a = int(policy.decide(game, 0).action)
                if not (0 <= a < 245 and bool(m[a])):
                    nz = np.flatnonzero(m)
                    a = int(nz[0]) if nz.size else 0
                if 196 <= a < 245:      # Move 段：196..244
                    turns[-1]["moves"] = int(turns[-1].get("moves", 0)) + 1
                if pend_opts is not None and 30 <= a < 46:
                    idx = a - 30
                    if (idx < len(pend_opts) and isinstance(pend_opts[idx], int)
                            and pend_opts[idx] in pend_carrier_eids):
                        casts_on_carrier += 1
                        turns[-1]["casts_on_carrier_turn"] = int(
                            turns[-1].get("casts_on_carrier_turn", 0)) + 1
                game.step(0, a)
                # 只取「learner 行动后、战斗前」的盘面，避免战斗死亡污染净盘面判定
                turns[-1]["board_end"] = _board_sig(game)
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    placements = list(game.placements())
    death_turn = None
    death_strength = None
    alive_rows = [row for row in turns if row["alive"]]
    if alive_rows:
        # 取死亡前最后一个「非空战团」回合；若最后一行恰好被清空（终局/战斗后），回退一格
        pick = alive_rows[-1]
        for row in reversed(alive_rows):
            if row["strength"] > 0:
                pick = row
                break
        death_turn, death_strength = pick["turn"], pick["strength"]
    return {"placement": int(placements[0]), "death_turn": death_turn,
            "death_strength": death_strength, "turns": turns,
            "carrier_turns": int(carrier_turns),
            "carrier_ever_on_board": bool(carrier_turns > 0),
            "carrier_shop_seen": bool(carrier_shop_seen),
            "casts_on_carrier": int(casts_on_carrier)}


class _ArenaPolicy:
    """把 ``scripts/arena_agent.act`` 包成 quality_monitor 的口径（部署路径离线复现）。

    观测直接喂本地引擎的 v1 字节（features 3227 / cards 124 / mask 245），所以必须
    ``ARENA_CARD_MAP=off``：本地 cards 已经是 37.0 下标，再走竞技场 36.6→37.0 映射
    会整体错位。守卫开关由 ``--move-guard/--move-cap/--move-repeat-limit`` 写进同名
    环境变量 —— 与线上部署**同一条代码路径**（见 docs/ARENA_GUARD.md）。

    每回合动作上限由**驱动侧**模拟竞技场的 ``context.action_limit``（默认 40，与训练
    评测路径 ``max_actions_per_turn`` 同口径）：达到上限后只允许 EndTurn。这是环境
    约束、不是 agent 逻辑；不加它，本地引擎不会像服务器那样强制结束回合，无守卫的
    策略会把 20,000 步预算刷满（truncation），短跑跑不完。
    """

    name = "arena_agent"

    def __init__(self, args) -> None:  # noqa: ANN001 - argparse.Namespace
        import scripts.arena_agent as AA
        self._AA = AA
        self._match = 0
        self._max_actions_per_turn = 40        # 竞技场 action_limit / 训练同口径
        self._turn_actions: dict = {}
        os.environ["ARENA_MODEL"] = os.path.abspath(args.checkpoint)
        os.environ["ARENA_DEVICE"] = str(args.device)
        os.environ["ARENA_CARD_MAP"] = "off"     # 本地观测已是 37.0 下标，不能映射
        os.environ["ARENA_MOVE_GUARD"] = "1" if int(args.move_guard) else "0"
        os.environ["ARENA_MOVE_CAP"] = str(int(args.move_cap))
        os.environ["ARENA_MOVE_REPEAT_LIMIT"] = str(int(args.move_repeat_limit))

    def reset(self) -> None:
        self._match += 1
        self._turn_actions = {}
        self._AA.reset_state()

    def move_guard_meta(self) -> dict:
        return self._AA.guard_meta()

    def decide(self, game, seat: int = 0):  # noqa: ANN001
        from types import SimpleNamespace
        raw = game.observe(int(seat))
        mask = mask_from_bytes(game.legal_mask(int(seat)))
        key = (int(self._match), int(seat), int(game.turn))
        n_used = int(self._turn_actions.get(key, 0)) + 1
        self._turn_actions[key] = n_used
        if n_used > self._max_actions_per_turn and bool(mask[0]):
            return SimpleNamespace(action=0, info={"forced": True})
        obs = {"features": np.frombuffer(raw[0], dtype=np.float32).copy(),
               "cards": np.frombuffer(raw[1], dtype=np.int32).copy(),
               "action_mask": mask.astype(np.uint8)}
        ctx = {"match_id": int(self._match), "seat": int(seat),
               "turn": int(game.turn)}
        return SimpleNamespace(action=int(self._AA.act(obs, ctx)), info={})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/champion_c0_1746.pt")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=256)
    ap.add_argument("--seed-base", type=int, default=520000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--calibration", default="data/real_library/strength_calibration.json")
    ap.add_argument("--policy", default="selfplay", choices=("selfplay", "arena"),
                    help="selfplay=训练侧策略（默认）；arena=走 scripts/arena_agent.act "
                         "的部署路径（换位守卫默认开，见 docs/ARENA_GUARD.md）")
    ap.add_argument("--move-guard", type=int, default=0, choices=[0, 1],
                    help="1=评测时也启用换位去抖守卫（默认 0=纯模型行为）")
    ap.add_argument("--move-cap", type=int, default=3,
                    help="每回合换位次数上限（仅 --move-guard 1 时生效；默认 3）")
    ap.add_argument("--move-repeat-limit", type=int, default=2,
                    help="同一 (from,to) 本回合出现 >=N 次后屏蔽（默认 2）")
    ap.add_argument("--out", default="runs/quality/quality.json")
    ap.add_argument("--carriers", default="data/scaling/carriers.json",
                    help="载体清单（docs/CARRIER_SCALING.md）；缺失时自动构建")
    ap.add_argument("--carrier-audit", type=int, default=1, choices=[0, 1],
                    help="1=面板里带 carrier_encounter_rate / casts_on_carrier_mean / "
                         "r(载体回合数, Σ12)")
    args = ap.parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2

    # ── 载体清单（与 scripts/carrier_audit.py 同源）──────────────────────
    carrier_ids: list = []
    cid2id: dict = {}
    if int(args.carrier_audit):
        try:
            from scripts.carrier_common import (CATALOG_OUT,
                                                ids_from_catalog,
                                                load_or_build_catalog)
            import json as _json
            import hsbg_engine as _E
            _cat = load_or_build_catalog(args.carriers)
            carrier_ids = sorted(ids_from_catalog(_cat, "primary"))
            cid2id = {int(c["cid"]): str(c["id"])
                      for c in _json.loads(_E.catalog_json())}
        except BaseException as exc:  # noqa: BLE001
            print(f"[warn] 载体清单不可用（{exc}）；跳过载体指标", file=sys.stderr)
            carrier_ids, cid2id = [], {}

    if args.policy == "arena":
        # 部署路径：checkpoint/设备/守卫全部由 arena_agent 的环境变量在 act 内消费。
        policy = _ArenaPolicy(args)
        cfg_dict = {"max_steps": int(args.max_steps)}
    else:
        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        ev = PPOEvaluator(model, device=args.device,
                          norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
        from hsbg.az.train.ppo import CollectConfig
        cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                            max_steps=int(args.max_steps),
                            move_guard=bool(int(args.move_guard)),
                            move_cap=int(args.move_cap),
                            move_repeat_limit=int(args.move_repeat_limit))
        policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                                   seed=int(args.seed_base), move_model=False)
        cfg_dict = cfg.__dict__

    rows = []
    if carrier_ids:
        cfg_dict = dict(cfg_dict or {})
        cfg_dict["carrier_ids"] = sorted(carrier_ids)
        cfg_dict["cid2id"] = dict(cid2id)
    for g in range(int(args.games)):
        r = _play(int(args.seed_base) + g, policy, cfg_dict)
        if r:
            rows.append(r)
    # 聚合：每 turn 的强度分位
    by_turn: dict[int, list[int]] = {}
    deaths: dict[int, list[int]] = {}
    tiers: dict[int, list[int]] = {}
    golds: dict[int, list[int]] = {}
    turn_moves: dict[int, list[int]] = {}
    all_turn_moves: list[int] = []
    net_unchanged = 0
    net_measured = 0
    move_legal_turns = 0
    move_turns = 0
    net_unchanged_move_turns = 0
    for r in rows:
        for row in r["turns"]:
            by_turn.setdefault(row["turn"], []).append(row["strength"])
            tiers.setdefault(row["turn"], []).append(row["tier"])
            golds.setdefault(row["turn"], []).append(row["gold"])
            n_mv = int(row.get("moves", 0) or 0)
            all_turn_moves.append(n_mv)
            turn_moves.setdefault(row["turn"], []).append(n_mv)
            if bool(row.get("move_legal")):
                move_legal_turns += 1
            if n_mv > 0:
                move_turns += 1
            be, bs = row.get("board_end"), row.get("board_start")
            if be is not None and bs is not None:
                net_measured += 1
                same = list(be) == list(bs)
                if same:
                    net_unchanged += 1
                if n_mv > 0 and same:
                    net_unchanged_move_turns += 1
        dt = r["death_turn"] or 0
        if r["placement"] > 1 and r["death_strength"] is not None:
            deaths.setdefault(dt, []).append(r["death_strength"])
    calib = {}
    if os.path.isfile(args.calibration):
        calib = json.load(open(args.calibration))
    summary = []
    for t in sorted(by_turn):
        v = np.asarray(by_turn[t])
        tv = np.asarray(tiers[t], dtype=np.int64)
        real = (calib.get(str(t)) or {}).get("real") or {}
        summary.append({
            "turn": t, "n": int(v.size),
            "ours_p50": float(np.percentile(v, 50)), "ours_p90": float(np.percentile(v, 90)),
            "ours_max": float(v.max()),
            "real_p50": real.get("p50"), "real_p75": real.get("p75"), "real_p90": real.get("p90"),
            "ratio_p50": (float(np.percentile(v, 50)) / real["p50"]) if real.get("p50") else None,
            "tier_p50": float(np.percentile(tiers[t], 50)),
            # tier≥5 / ≥6 比例（本 turn 全部局）：DPO A/B 的主判据之一
            "tier_ge5_ratio": float(np.mean(tv >= 5)),
            "tier_ge6_ratio": float(np.mean(tv >= 6)),
            "gold_p50": float(np.percentile(golds[t], 50)),
            "moves_mean": float(np.mean(turn_moves[t])),
            "moves_max": int(np.max(turn_moves[t])),
        })
    if deaths:
        all_deaths = [s for v in deaths.values() for s in v]
        death_turns = [t for t, v in deaths.items() for _ in v]
    else:
        all_deaths, death_turns = [], []
    out = {"checkpoint": args.checkpoint, "games": len(rows),
           "policy": args.policy,
           "seed_base": int(args.seed_base),
           "placements": [r["placement"] for r in rows],
           "mean_rank": float(np.mean([r["placement"] for r in rows])) if rows else None,
           "top4": float(np.mean([r["placement"] <= 4 for r in rows])) if rows else None,
           "win": float(np.mean([r["placement"] == 1 for r in rows])) if rows else None,
           "death_turn_hist": {str(t): len(v) for t, v in sorted(deaths.items())},
           "death_strength_p50": float(np.percentile(all_deaths, 50)) if all_deaths else None,
           "death_strength_mean": float(np.mean(all_deaths)) if all_deaths else None,
           "by_turn": summary,
           "death_turn_p50": float(np.percentile(death_turns, 50)) if death_turns else None,
           # ── 换位去抖（guard）指标 ──
           "move_guard": bool(int(args.move_guard)),
           "move_cap": int(args.move_cap),
           "move_repeat_limit": int(args.move_repeat_limit),
           "turns_total": int(len(all_turn_moves)),
           "move_actions_total": int(sum(all_turn_moves)),
           "moves_per_turn_mean": (float(np.mean(all_turn_moves))
                                   if all_turn_moves else 0.0),
           "moves_per_turn_p50": (float(np.percentile(all_turn_moves, 50))
                                  if all_turn_moves else 0.0),
           "moves_per_turn_p90": (float(np.percentile(all_turn_moves, 90))
                                  if all_turn_moves else 0.0),
           "moves_per_turn_max": int(np.max(all_turn_moves)) if all_turn_moves else 0,
           "turns_with_move": int(sum(1 for v in all_turn_moves if v > 0)),
           "turns_with_move_ratio": (float(np.mean([1.0 if v > 0 else 0.0
                                                    for v in all_turn_moves]))
                                     if all_turn_moves else 0.0),
           "move_legal_turns": int(move_legal_turns),
           "moves_per_move_legal_turn_mean": (float(sum(all_turn_moves))
                                              / move_legal_turns
                                              if move_legal_turns else 0.0),
           "move_turns": int(move_turns),
           "moves_per_move_turn_mean": (float(sum(all_turn_moves)) / move_turns
                                       if move_turns else 0.0),
           "net_board_unchanged_turns": int(net_unchanged),
           "net_board_unchanged_measured": int(net_measured),
           "net_board_unchanged_ratio": (float(net_unchanged) / net_measured
                                         if net_measured else 0.0),
           "net_board_unchanged_move_turns": int(net_unchanged_move_turns),
           "net_board_unchanged_move_ratio": (float(net_unchanged_move_turns)
                                              / move_turns if move_turns else 0.0),
           "tier_p50_t9": (next((row["tier_p50"] for row in summary
                                 if row["turn"] == 9), None)),
           "tier_p50_t12": (next((row["tier_p50"] for row in summary
                                  if row["turn"] == 12), None)),
           "tier_p50_t15": (next((row["tier_p50"] for row in summary
                                  if row["turn"] == 15), None)),
           # tier≥5 比例（turn 9/12/15）：upgrade DPO 的主判据（docs/DPO_UPGRADE.md）
           "tier_ge5_t9": (next((row["tier_ge5_ratio"] for row in summary
                                 if row["turn"] == 9), None)),
           "tier_ge5_t12": (next((row["tier_ge5_ratio"] for row in summary
                                  if row["turn"] == 12), None)),
           "tier_ge5_t15": (next((row["tier_ge5_ratio"] for row in summary
                                  if row["turn"] == 15), None)),
           # 战团强度比（ours_p50 / real_p50，turn 9/12/15）
           "strength_ratio_t9": (next((row["ratio_p50"] for row in summary
                                       if row["turn"] == 9), None)),
           "strength_ratio_t12": (next((row["ratio_p50"] for row in summary
                                        if row["turn"] == 12), None)),
           "strength_ratio_t15": (next((row["ratio_p50"] for row in summary
                                        if row["turn"] == 15), None)),
           "move_guard_meta": policy.move_guard_meta()}
    out.update(_carrier_panel(rows, carrier_ids))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps({k: out.get(k) for k in (
        "games", "policy", "move_guard", "mean_rank", "top4", "win", "death_turn_p50",
        "death_strength_p50",
        "moves_per_turn_mean", "moves_per_turn_p90", "moves_per_turn_max",
        "moves_per_turn_p50", "turns_with_move",
        "net_board_unchanged_ratio",
        "moves_per_move_legal_turn_mean", "moves_per_move_turn_mean",
        "net_board_unchanged_turns",
        "net_board_unchanged_move_turns", "net_board_unchanged_move_ratio",
        "tier_p50_t9", "tier_p50_t12", "tier_p50_t15",
        "tier_ge5_t9", "tier_ge5_t12", "tier_ge5_t15",
        "strength_ratio_t9", "strength_ratio_t12", "strength_ratio_t15",
        "carrier_encounter_rate", "carrier_t9_rate", "casts_on_carrier_mean",
        "r_carrier_turns_str12", "r_carrier_turns_str12_ci95")},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
