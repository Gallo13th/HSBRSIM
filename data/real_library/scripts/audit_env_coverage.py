#!/usr/bin/env python
"""RL 环境接口覆盖度审计（回归门禁）。

用启发式 / 随机策略跑 N 局，统计「观测-动作-选择-回合」接口的真实覆盖，
输出 JSON 并给出 PASS/FAIL 门禁。对应文档: ``docs/ENV_INTERFACE_GAPS.md``。

审计指标
--------
1. **动作覆盖**: 每类 `ActionKind` 的候选数/实际执行数；目标变体
   （定向法术 / 定向战吼 / 定向英雄技能 / 双目标技能 / 磁力吸附）。
2. **英雄技能可用性**: 池内 118 英雄中 `needs_target` 的技能逐个做
   synthetic 场景验证（候选存在 + `apply_action` 成功），并统计真实对局里
   带目标技能候选出现次数。
3. **选择步**: PendingChoice kind 分布（choose 候选数、任务/饰品/Dark
   Gift/发现等）。
4. **裁剪**: `candidates_generated/trimmed`、`plays_dropped`、
   `max_candidates(_generated)`——量化 CANDIDATE_MAX=64 的裁剪频率。
5. **非法/无进展**: `invalid`（非候选动作）、`engine_rejected`（候选被引擎
   拒绝）、`noop_actions`（状态指纹无变化的动作）、`budget_exhausted`。
6. **未覆盖卡**: 观测中出现过（可见区域）但从未被任何候选动作引用的卡，
   按「池内/数据链 token/脚本字面量 token/不可打出」分类。
7. **观测补全**: `info["obs_extra"]` 关键字段在真实对局中的非默认值计数
   （frozen / 技能次数 / 任务进度 / Dark Gift / 战斗结果等）。

用法::

    python scripts/audit_env_coverage.py --games 20
    python scripts/audit_env_coverage.py --games 20 --agent mixed --json runs/env_coverage.json
    python scripts/audit_env_coverage.py --games 20 --players 8 --no-gate   # 仅报告

退出码: 0=门禁通过, 1=有硬性失败（invalid/engine_rejected>0 或关键类别 0 覆盖）。
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.agents.base import choose_option_index  # noqa: E402
from hsbg.agents.heuristic import HeuristicPolicy  # noqa: E402
from hsbg.agents.random_agent import RandomPolicy  # noqa: E402
from hsbg.env import BattlegroundsEnv, driver  # noqa: E402
from hsbg.env.spec import (  # noqa: E402
    CANDIDATE_MAX,
    ActionKind,
    CandidateAction,
)

ACTION_KINDS = tuple(k.value for k in ActionKind)

#: 所有候选类别（审计要求每类至少出现 1 次的门禁子集）
GATE_KINDS = (
    "buy", "sell", "play_minion", "play_spell", "reroll", "upgrade",
    "freeze", "hero_power", "activate", "use_dark_gift", "end_turn",
)


def _pick(policy: Any, env: BattlegroundsEnv, obs: Any) -> CandidateAction:
    if obs.phase == "choice":
        return CandidateAction(
            kind=ActionKind.CHOOSE.value,
            option=choose_option_index(policy, obs, env.game))
    desc = policy.choose(env.game, env.agent_hero)
    if desc is None:
        return CandidateAction(kind=ActionKind.END_TURN.value)
    return desc.to_candidate()


def _check_slot_consistency(step_actions: Any) -> int:
    """候选动作的槽位与观测槽位同源校验（返回不一致数）。

    对每个 descriptor：若 ``src_entity/tgt_entity`` 在本步 Zones 可寻址，
    则对应 ``CandidateAction.src_zone/slot`` 必须指向同一 ``(zone, slot)``。
    这类不一致会让策略"选的候选指向错实体"，必须为 0。
    """
    bad = 0
    zones = step_actions.zones
    for d, cand in zip(step_actions.descriptors, step_actions.candidates):
        for ent, zone, slot in ((d.src_entity, cand.src_zone, cand.src_slot),
                                (d.tgt_entity, cand.tgt_zone, cand.tgt_slot)):
            if ent is None:
                continue
            loc = zones.locate(ent)
            if loc is None:
                continue
            if (zone, slot) != loc:
                bad += 1
    return bad


def _visible_card_ids(obs: Any) -> List[Tuple[str, str]]:
    out = []
    for zone, arr in (("board", obs.board), ("hand", obs.hand),
                      ("tavern", obs.tavern), ("trinket", obs.trinkets),
                      ("opponent", obs.opponent_board)):
        for tok in arr:
            if tok.card_id:
                out.append((zone, tok.card_id))
    if obs.quest is not None and obs.quest.card_id:
        out.append(("quest", obs.quest.card_id))
    return out


#: 观测 v2 `extra` 必须存在的契约键（缺任何键 → 门禁失败）
EXTRA_REQUIRED_KEYS = (
    "version", "turn",
    "frozen_tavern", "free_refresh_left", "refresh_cost",
    "gold_spent_this_turn", "cards_played_this_turn",
    "powers", "power_uses_left", "second_power_id",
    "dark_gift", "dark_gift_uses_left",
    "quest", "quest_progress", "quest_target", "quest_reward_ids",
    "trinkets", "trinket_ids",
    "board_states", "hand_states", "minion_flags",
    "pending_hand_queue", "pending_hand_card_ids",
    "next_opponent", "last_opponent",
    "next_opponent_info", "last_opponent_info",
    "elimination", "elimination_order",
    "last_combat", "deaths_by_card_id",
)


def _obs_extra_counts(obs: Any, acc: Dict[str, Any]) -> None:
    """统计观测 v2 ``obs.extra`` 的键覆盖与出现率（含缺失键门禁）。"""
    extra = getattr(obs, "extra", None) or {}
    if not extra:
        acc["obs_extra"]["obs_extra_missing"] = acc["obs_extra"].get(
            "obs_extra_missing", 0) + 1
        return
    acc["obs_extra"]["obs_extra_steps"] = acc["obs_extra"].get(
        "obs_extra_steps", 0) + 1
    for key in EXTRA_REQUIRED_KEYS:
        if key not in extra:
            acc["extra_missing_keys"][key] += 1
    if extra.get("version") != obs.version:
        acc["obs_extra"]["extra_version_mismatch"] = acc["obs_extra"].get(
            "extra_version_mismatch", 0) + 1
    if extra.get("frozen_tavern"):
        acc["obs_extra"]["frozen_tavern_true"] = acc["obs_extra"].get(
            "frozen_tavern_true", 0) + 1
    if extra.get("free_refresh_left"):
        acc["obs_extra"]["free_refresh_true"] = acc["obs_extra"].get(
            "free_refresh_true", 0) + 1
    if (extra.get("dark_gift") or {}).get("enabled"):
        acc["obs_extra"]["dark_gift_enabled"] = acc["obs_extra"].get(
            "dark_gift_enabled", 0) + 1
    if extra.get("quest") is not None:
        acc["obs_extra"]["quest_present"] = acc["obs_extra"].get(
            "quest_present", 0) + 1
    if int(extra.get("quest_progress") or 0) > 0:
        acc["obs_extra"]["quest_progress_positive"] = acc["obs_extra"].get(
            "quest_progress_positive", 0) + 1
    if extra.get("trinkets"):
        acc["obs_extra"]["trinket_present"] = acc["obs_extra"].get(
            "trinket_present", 0) + 1
    if int(extra.get("pending_hand_queue") or 0):
        acc["obs_extra"]["pending_hand_queue"] = acc["obs_extra"].get(
            "pending_hand_queue", 0) + 1
    if extra.get("last_combat"):
        acc["obs_extra"]["combat_result_present"] = acc["obs_extra"].get(
            "combat_result_present", 0) + 1
    if extra.get("elimination"):
        acc["obs_extra"]["elimination_present"] = acc["obs_extra"].get(
            "elimination_present", 0) + 1
    if extra.get("elimination_order"):
        acc["obs_extra"]["elimination_order_present"] = acc["obs_extra"].get(
            "elimination_order_present", 0) + 1
    if extra.get("next_opponent"):
        acc["obs_extra"]["next_opponent_present"] = acc["obs_extra"].get(
            "next_opponent_present", 0) + 1
    powers = extra.get("powers") or []
    if powers:
        acc["obs_extra"]["powers_present"] = acc["obs_extra"].get(
            "powers_present", 0) + 1
    if extra.get("second_power_id"):
        acc["obs_extra"]["second_power_slot"] = acc["obs_extra"].get(
            "second_power_slot", 0) + 1
    if extra.get("minion_flags"):
        acc["obs_extra"]["minion_flags_present"] = acc["obs_extra"].get(
            "minion_flags_present", 0) + 1
    for p in powers:
        if p.get("needs_target"):
            acc["obs_extra"]["targeted_power_present"] = acc["obs_extra"].get(
                "targeted_power_present", 0) + 1
    for st in extra.get("board_states") or []:
        if st.get("exhausted"):
            acc["obs_extra"]["board_exhausted"] = acc["obs_extra"].get(
                "board_exhausted", 0) + 1
        if st.get("frozen"):
            acc["obs_extra"]["board_frozen"] = acc["obs_extra"].get(
                "board_frozen", 0) + 1
        if st.get("activate_used_this_turn"):
            acc["obs_extra"]["board_activate_used"] = acc["obs_extra"].get(
                "board_activate_used", 0) + 1


def run_episode(players: int, seed: int, policy: Any,
                acc: Dict[str, Any]) -> Dict[str, Any]:
    env = BattlegroundsEnv(num_players=players, opponent="heuristic",
                           seed=seed, max_turns=40)
    obs = env.reset(seed=seed)
    t0 = time.perf_counter()
    steps = 0
    invalid = 0
    rejected = 0
    rewards: List[float] = []
    info: Dict[str, Any] = {}
    while True:
        steps += 1
        cand_counts = collections.Counter(c.kind for c in obs.candidates)
        for kind, n in cand_counts.items():
            acc["candidates_by_kind"][kind] += n
        acc["candidate_steps"] += 1
        acc["candidates_total"] += len(obs.candidates)
        acc["candidates_max"] = max(acc["candidates_max"],
                                    len(obs.candidates))
        if obs.pending_choice is not None:
            acc["choice_kinds"][obs.pending_choice.kind] += 1
        # 观测可见卡 / 候选引用卡
        for _zone, cid in _visible_card_ids(obs):
            acc["visible_cards"][cid] += 1
        step_actions = getattr(env, "_step_actions", None)
        if step_actions is not None:
            for d in step_actions.descriptors:
                for ent in (d.src_entity, d.tgt_entity):
                    cid = getattr(ent, "card_id", None)
                    if cid:
                        acc["referenced_cards"][str(cid)] += 1
            acc["candidate_slot_consistent"] = (
                acc.get("candidate_slot_consistent", 0)
                + _check_slot_consistency(step_actions))
        action = _pick(policy, env, obs)
        applied_kind = action.kind
        obs, reward, terminated, truncated, info = env.step(action)
        rewards.append(float(reward))
        if info.get("invalid"):
            invalid += 1
            if info.get("action_error_type") == "Rejected":
                rejected += 1
        elif applied_kind != "end_turn":
            acc["applied_by_kind"][applied_kind] += 1
        _obs_extra_counts(obs, acc)
        if info.get("obs_extra") is not None and info.get("obs_extra") != \
                obs.extra:
            acc["obs_extra"]["obs_extra_mismatch"] = acc["obs_extra"].get(
                "obs_extra_mismatch", 0) + 1
        if terminated or truncated:
            break
        if steps > 4000:                                  # 防御性护栏
            acc["step_cap_hit"] += 1
            break
    elapsed = time.perf_counter() - t0
    stats = env.stats
    env.close()
    return {
        "seed": seed, "steps": steps, "turns": int(info.get("turn", 0)),
        "rank": int(info.get("rank", 0)),
        "terminated": bool(info.get("terminated_reason")),
        "invalid": invalid, "engine_rejected": rejected,
        "elapsed": elapsed,
        "stats": dict(stats),
        "rewards_finite": all(r == r and abs(r) != float("inf")
                              for r in rewards),
    }


def audit_hero_power_targets(acc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """synthetic 审计: 每个 `needs_target` 英雄技能能否生成并执行候选。"""
    from hsrl2.db import CardDB
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.scripts import REGISTRY
    from hsrl2.tags import GameTag

    db = driver.get_card_db()
    results: List[Dict[str, Any]] = []
    heroes = [d for d in db._by_id.values()
              if getattr(d, "card_type", None) is not None
              and int(getattr(d, "card_type", -1)) == 3]
    for hd in heroes:
        pid = getattr(hd, "hero_power_id", None)
        script = REGISTRY.get(pid) if pid else None
        if script is None or not getattr(script, "needs_target", False):
            continue
        acc["targeted_powers_total"] += 1
        a, b = Hero(hd.id, "A"), Hero("TEST_B", "B")
        game = Game([a, b], db, seed=3)
        game.start_game()
        driver.resolve_pending_choices(game, None)
        # 让"第 N 回合起解锁 / Tier 门槛"类技能的 available() 通过
        game.turn = max(int(game.turn), 6)
        a.set(GameTag.TAVERN_TIER, 4)
        a.gold = 40
        for cid in ("BG25_001", "BGS_119", "BG25_008"):
            m = game.create_minion(cid, controller=a)
            game.summon(a, m)
        # 带战吼的随从（TB_BaconShop_HP_022 "Trigger a friendly Battlecry"）
        m = game.create_minion("BG36_112", controller=a)
        game.summon(a, m)
        for cid in ("BG25_001",):
            m = game.create_minion(cid, controller=a)
            a.add_to_hand(m)
        game.refresh_tavern(a)
        descs = [d for d in driver.enumerate_actions(game, a)
                 if d.kind == ActionKind.HERO_POWER.value]
        with_target = [d for d in descs if d.tgt_entity is not None]
        dual = [d for d in descs if getattr(d, "note", "") == "targets=2"]
        ok = False
        detail = ""
        if not descs:
            # 区分"引擎语义上暂不可用"（available()==False）与枚举缺口
            try:
                avail = (script.available(a, game)
                         if getattr(script, "available", None) else True)
            except Exception:                             # noqa: BLE001
                avail = True
            detail = ("available_false" if not avail
                      else "no_candidate_but_available")
        else:
            candidate = (with_target or dual or descs)
            res = driver.apply_action(game, a, candidate[0])
            if res.success:
                ok = True
                driver.resolve_pending_choices(game, None)
            else:
                detail = f"{res.error_type}:{res.error}"[:120]
        if with_target:
            acc["targeted_power_with_variant"] += 1
        if dual:
            acc["targeted_power_dual"] += 1
        if ok:
            acc["targeted_power_apply_ok"] += 1
        results.append({
            "hero_id": hd.id, "power_id": pid,
            "target_count": int(getattr(script, "target_count", 1)),
            "variants": len(with_target), "dual_variant": bool(dual),
            "apply_ok": ok, "detail": detail,
        })
    return results


#: 可操作性 synthetic 状态覆盖的种族（定向目标过滤的主要类型）
_OPERABILITY_RACES = ("DEMON", "UNDEAD", "BEAST", "DRAGON", "PIRATE")


def _pool_card_of_race(race_name: str) -> Optional[str]:
    """返回池内首个该种族的随从卡 id（用于 synthetic 目标状态）。"""
    db = driver.get_card_db()
    for d in db.pool_minions():
        for r in getattr(d, "races", ()):
            if getattr(r, "name", "") == race_name:
                return d.id
    return None


def _synthetic_operable(cid: str) -> Optional[bool]:
    """synthetic 可操作性检查: 该卡在手牌/酒馆中是否能生成合法候选。

    返回 ``True``（能生成并 apply 成功）/ ``False``（无候选）/ ``None``
    （不可打出的卡 / 数据缺失，不参与判定）。
    """
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.tags import CardType

    db = driver.get_card_db()
    d = db.get(cid)
    if d is None or getattr(d, "unplayable", False):
        return None
    a, b = Hero("TEST_A", "A"), Hero("TEST_B", "B")
    game = Game([a, b], db, seed=3)
    game.start_game()
    driver.resolve_pending_choices(game, None)
    a.gold = 80
    try:
        is_minion = int(getattr(d, "card_type", -1)) == int(
            CardType.MINION)
        if is_minion:
            m = game.create_minion(cid, controller=a)
            a.add_to_hand(m)
            descs = [x for x in driver.enumerate_actions(game, a)
                     if x.kind == ActionKind.PLAY_MINION.value
                     and x.src_entity is m]
            if descs:
                return driver.apply_action(game, a, descs[0]).success
            # 手牌打出不可用（不可打出/锁定）时再看酒馆购买
            t_ent = game.create_minion(cid, controller=a)
            game.add_tavern_entity(a, t_ent)
            buy = [x for x in driver.enumerate_actions(game, a)
                   if x.kind == ActionKind.BUY.value
                   and x.src_entity is t_ent]
            return bool(buy) and driver.apply_action(game, a, buy[0]).success
        # 定向法术需要目标→给棋盘多种族真实池随从（"正常对局状态"口径；
        # 覆盖按种族过滤的 target_candidates，如 "a Demon"/"a Beast"）
        for race in _OPERABILITY_RACES:
            cid_pool = _pool_card_of_race(race)
            if cid_pool is not None:
                game.summon(a, game.create_minion(cid_pool, controller=a))
        s = game.create_spell(cid, controller=a)
        a.add_to_hand(s)
        descs = [x for x in driver.enumerate_actions(game, a)
                 if x.kind == ActionKind.PLAY_SPELL.value
                 and x.src_entity is s]
        return bool(descs) and driver.apply_action(game, a, descs[0]).success
    except Exception:                                     # noqa: BLE001
        return False


def classify_unreferenced(never: List[str]) -> Dict[str, List[str]]:
    """未覆盖卡分类: 池内 / 数据链 token / 脚本字面量 token / 不可打出。"""
    from hsrl2.scripts import REGISTRY
    db = driver.get_card_db()
    # 数据链: 任意 def 的 evolution/triple/spellcraft/companion 指向该卡 dbf
    linked_dbfs: set = set()
    for d in db._by_id.values():
        for attr in ("evolution_card_id", "triple_base_id",
                     "triple_upgrade_id", "spellcraft_id", "companion_id",
                     "reward_dbf_id"):
            v = getattr(d, attr, None)
            if isinstance(v, int):
                linked_dbfs.add(v)
    # 脚本源码里被字面量引用的卡 id（粗粒度: 扫描 batches 文本）
    script_text = ""
    for p in (ROOT / "hsrl2" / "scripts").rglob("*.py"):
        try:
            script_text += p.read_text(encoding="utf-8", errors="ignore")
        except OSError:                                   # pragma: no cover
            continue
    out: Dict[str, List[str]] = collections.defaultdict(list)
    for cid in never:
        d = db.get(cid)
        if d is None:
            out["missing_card_def"].append(cid)
            continue
        if getattr(d, "unplayable", False):
            out["unplayable"].append(cid)
        elif getattr(d, "is_pool_minion", False):
            ok = _synthetic_operable(cid)
            out["pool_minion_operable_not_sampled" if ok
                else "pool_minion_no_candidate_BUG"].append(cid)
        elif getattr(d, "is_pool_spell", False):
            ok = _synthetic_operable(cid)
            out["pool_spell_operable_not_sampled" if ok
                else "pool_spell_no_candidate_BUG"].append(cid)
        elif d.dbf_id in linked_dbfs:
            out["token_data_chain"].append(cid)
        elif f'"{cid}"' in script_text:
            out["token_script_literal"].append(cid)
        elif cid in REGISTRY:
            out["registered_never_seen"].append(cid)
        else:
            out["unreferenced_no_evidence"].append(cid)
    return dict(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="RL env interface coverage audit")
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--agent", default="heuristic",
                    choices=("heuristic", "random", "mixed"))
    ap.add_argument("--json", default=None)
    ap.add_argument("--no-gate", action="store_true",
                    help="只报告，不因门禁失败返回非 0")
    args = ap.parse_args(argv)

    acc: Dict[str, Any] = {
        "candidates_by_kind": collections.Counter(),
        "applied_by_kind": collections.Counter(),
        "choice_kinds": collections.Counter(),
        "candidate_steps": 0,
        "candidates_total": 0,
        "candidates_max": 0,
        "visible_cards": collections.Counter(),
        "referenced_cards": collections.Counter(),
        "obs_extra": collections.Counter(),
        "extra_missing_keys": collections.Counter(),
        "step_cap_hit": 0,
        "candidate_slot_consistent": 0,
        "targeted_powers_total": 0,
        "targeted_power_with_variant": 0,
        "targeted_power_apply_ok": 0,
        "targeted_power_dual": 0,
    }
    t0 = time.perf_counter()
    games = []
    for i in range(args.games):
        seed = args.seed + i
        if args.agent == "heuristic":
            policy = HeuristicPolicy()
        elif args.agent == "random":
            policy = RandomPolicy(end_turn_prob=0.15)
        else:
            policy = HeuristicPolicy() if i % 2 == 0 else \
                RandomPolicy(end_turn_prob=0.15)
        games.append(run_episode(args.players, seed, policy, acc))
    elapsed = time.perf_counter() - t0

    hp_results = audit_hero_power_targets(acc)

    visible = set(acc["visible_cards"])
    referenced = set(acc["referenced_cards"])
    never = sorted(visible - referenced)
    never_class = classify_unreferenced(never)

    # 汇总 env.stats（消除跨局累加为单局均值/总和）
    stats_keys = ("candidates_generated", "candidates_trimmed",
                  "plays_dropped", "budget_exhausted", "noop_actions",
                  "choice_steps", "max_candidates", "max_candidates_generated",
                  "hero_power_targeted", "play_minion_targeted",
                  "play_spell_targeted", "magnetic_attach",
                  "dual_target_power_candidates")
    stats_sum = {k: sum(int(g["stats"].get(k, 0)) for g in games)
                 for k in stats_keys}
    # max_* 不能求和（那是每局的最大值）
    stats_sum["max_candidates"] = max(
        int(g["stats"].get("max_candidates", 0)) for g in games)
    stats_sum["max_candidates_generated"] = max(
        int(g["stats"].get("max_candidates_generated", 0)) for g in games)
    invalid = sum(g["invalid"] for g in games)
    rejected = sum(g["engine_rejected"] for g in games)
    steps = sum(g["steps"] for g in games)

    summary = {
        "games": len(games),
        "players": args.players,
        "agent": args.agent,
        "steps": steps,
        "wall_seconds": round(elapsed, 2),
        "steps_per_second": round(steps / elapsed, 2) if elapsed else 0,
        "avg_candidates": round(acc["candidates_total"]
                                / max(1, acc["candidate_steps"]), 2),
        "max_candidates": acc["candidates_max"],
        "candidate_cap": CANDIDATE_MAX,
        "trim_ratio": round(stats_sum["candidates_trimmed"]
                            / max(1, stats_sum["candidates_generated"]), 4),
        "invalid": invalid,
        "invalid_rate": round(invalid / max(1, steps), 6),
        "engine_rejected": rejected,
        "engine_rejected_rate": round(rejected / max(1, steps), 6),
        "noop_actions": stats_sum["noop_actions"],
        "budget_exhausted": stats_sum["budget_exhausted"],
        "choice_steps": sum(acc["choice_kinds"].values()),
        "turns_mean": round(statistics.fmean(g["turns"] for g in games), 2),
        "rank_mean": round(statistics.fmean(g["rank"] for g in games), 3),
    }
    coverage = {
        "candidates_by_kind": dict(acc["candidates_by_kind"]),
        "applied_by_kind": dict(acc["applied_by_kind"]),
        "choice_kinds": dict(acc["choice_kinds"]),
        "target_variants": {
            "hero_power_targeted_candidates": stats_sum["hero_power_targeted"],
            "dual_target_power_candidates":
                stats_sum["dual_target_power_candidates"],
            "play_minion_targeted_candidates":
                stats_sum["play_minion_targeted"],
            "play_spell_targeted_candidates":
                stats_sum["play_spell_targeted"],
            "magnetic_attach_candidates": stats_sum["magnetic_attach"],
        },
        "pruning": {
            "candidates_generated": stats_sum["candidates_generated"],
            "candidates_trimmed": stats_sum["candidates_trimmed"],
            "plays_dropped": stats_sum["plays_dropped"],
            "max_candidates": stats_sum["max_candidates"],
            "max_candidates_generated":
                stats_sum["max_candidates_generated"],
            "trim_ratio": summary["trim_ratio"],
        },
        "obs_extra": dict(acc["obs_extra"]),
        "extra_missing_keys": dict(acc["extra_missing_keys"]),
        "hero_power_target_synthetic": {
            "targeted_powers": acc["targeted_powers_total"],
            "with_variant": acc["targeted_power_with_variant"],
            "apply_ok": acc["targeted_power_apply_ok"],
            "dual_target_powers": acc["targeted_power_dual"],
            "failures": [r for r in hp_results
                         if not r["apply_ok"]],
        },
        "visible_cards": len(visible),
        "referenced_cards": len(referenced),
        "slot_inconsistencies": acc["candidate_slot_consistent"],
        "never_referenced": never,
        "never_referenced_class": never_class,
    }

    # ── 门禁 ──
    failures: List[str] = []
    if invalid:
        failures.append(f"invalid_actions={invalid}")
    if rejected:
        failures.append(f"engine_rejected={rejected}")
    for kind in GATE_KINDS:
        if acc["candidates_by_kind"].get(kind, 0) <= 0:
            failures.append(f"action_kind_never_offered:{kind}")
    for key in ("play_spell_targeted_candidates",
                "play_minion_targeted_candidates",
                "magnetic_attach_candidates"):
        if coverage["target_variants"][key] <= 0:
            failures.append(f"target_variant_never_offered:{key}")
    if acc["targeted_powers_total"]:
        hard_hp = [r for r in hp_results
                   if not r["apply_ok"] and r["detail"] != "available_false"]
        if hard_hp:
            failures.append(
                "hero_power_target_variant_missing:"
                f"{len(hard_hp)}/{acc['targeted_powers_total']} "
                f"({[r['hero_id'] for r in hard_hp]})")
    if coverage["pruning"]["plays_dropped"] > 0:
        failures.append(
            f"hand_play_groups_dropped={coverage['pruning']['plays_dropped']}")
    pool_bug = (coverage["never_referenced_class"].get(
                    "pool_minion_no_candidate_BUG", [])
                + coverage["never_referenced_class"].get(
                    "pool_spell_no_candidate_BUG", []))
    if pool_bug:
        failures.append(f"pool_card_no_candidate:{pool_bug}")
    if acc["step_cap_hit"]:
        failures.append(f"step_cap_hit={acc['step_cap_hit']}")
    if acc["extra_missing_keys"]:
        failures.append(
            "obs_extra_missing_keys:"
            f"{dict(acc['extra_missing_keys'])}")
    if coverage["obs_extra"].get("obs_extra_missing"):
        failures.append(
            "obs_extra_empty_steps="
            f"{coverage['obs_extra']['obs_extra_missing']}")
    if coverage["obs_extra"].get("obs_extra_mismatch"):
        failures.append(
            "obs_extra_vs_info_mismatch="
            f"{coverage['obs_extra']['obs_extra_mismatch']}")
    if not coverage["obs_extra"].get("powers_present"):
        failures.append("obs_extra_no_powers")
    if not (coverage["obs_extra"].get("frozen_tavern_true")
            or coverage["obs_extra"].get("free_refresh_true")):
        failures.append("obs_extra_no_freeze_or_free_refresh")
    if acc["candidate_slot_consistent"]:
        failures.append(
            "candidate_slot_inconsistencies="
            f"{acc['candidate_slot_consistent']}")
    if any(not g["rewards_finite"] for g in games):
        failures.append("non_finite_reward")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": summary,
        "coverage": coverage,
        "gates": {"failures": failures, "ok": not failures},
        "games": [{k: v for k, v in g.items() if k != "stats"}
                  for g in games],
        "hero_power_results": hp_results,
    }
    print(json.dumps({k: report[k] for k in ("timestamp", "summary",
                                             "coverage", "gates")},
                     ensure_ascii=False, indent=2))
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print(f"saved: {p}")
    if failures and not args.no_gate:
        print("\nGATE FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nGATE PASS: all interface coverage checks satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
