"""比较口径与分类。

分类集合（docs/CONFORMANCE_AUTOTAVERN.md §4）：
* ``MATCH``：可观察语义一致（胜负分布/伤害/机制不变量）；
* ``CONVENTION_DIFF``：差异来自约定或参照侧实现差异，hsrl2 无 (a) RNG 流/
  随机目标顺序等约定；(b) 参照侧脚本/实现异常（AC-04，F-35 控制实验）；

* ``ENGINE_BUG``：可用最小复现固定下来的行为/规则分歧（hsrl2 与参照
  AutoTavern + 官方规则不一致）；
* ``DATA_GAP``：卡牌/版本数据缺口（卡缺失、属性/关键词不一致），不是
  引擎行为错误；
* ``UNSUPPORTED``：参照侧 Python API 无法构造等价局面；
* ``DEFERRED``：已观测到分歧但无法归责（参照侧实现/版本/证据不足），
  登记待裁定、不改 hsrl2（审计状态，不属初版 5 分类；见台账 AC-04）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def distribution(wins: Dict[str, int], n: int) -> Dict[str, float]:
    if n <= 0:
        return {"a": 0.0, "b": 0.0, "tie": 0.0}
    return {k: wins.get(k, 0) / n for k in ("a", "b", "tie")}


def _mean(xs: List[int]) -> Optional[float]:
    return (sum(xs) / len(xs)) if xs else None


def damage_summary(dmg: Dict[str, List[int]]) -> Dict[str, Any]:
    return {
        "a_mean": _mean(dmg.get("a") or []),
        "b_mean": _mean(dmg.get("b") or []),
        "a_values": sorted(set(dmg.get("a") or [])),
        "b_values": sorted(set(dmg.get("b") or [])),
    }


def _cat_max_diff(pt: Dict[str, float], ph: Dict[str, float]) -> float:
    return max(abs(pt[k] - ph[k]) for k in ("a", "b", "tie"))


def compare_duel(tavern_obs: Dict[str, Any], hs_obs: Dict[str, Any],
                 *, dist_tol: float = 0.25,
                 damage_mean_tol: float = 1.5) -> Dict[str, Any]:
    """比较两侧战斗观察，返回 verdict + 细节。

    输入形状：
    * tavern_obs: {"wins": {...}, "damage_by_winner": {...}, "n": N,
                   "sample": {...}}（n 个独立 trial）
    * hs_obs: HSRL2 run_trials() 的返回（N 个 seed）
    """
    n = min(int(tavern_obs.get("n") or 0), int(hs_obs.get("n") or 0))
    pt = distribution(tavern_obs["wins"], n)
    ph = distribution(hs_obs["wins"], n)
    dt = damage_summary(tavern_obs["damage_by_winner"])
    dh = damage_summary(hs_obs["damage_by_winner"])
    detail: Dict[str, Any] = {
        "n": n,
        "tavern_win_rate": pt,
        "hsrl2_win_rate": ph,
        "win_rate_max_diff": _cat_max_diff(pt, ph),
        "tavern_damage": dt,
        "hsrl2_damage": dh,
        "tavern_truncated": int(tavern_obs.get("truncated") or 0),
        "hsrl2_truncated": int(hs_obs.get("truncated") or 0),
        "hsrl2_errors": list(hs_obs.get("errors") or [])[:3],
    }
    # 确定性判定：两侧都只有一个结果类别时要求胜负与伤害完全一致
    t_single = [k for k, v in tavern_obs["wins"].items() if v == n]
    h_single = [k for k, v in hs_obs["wins"].items() if v == n]
    detail["tavern_single_outcome"] = t_single[0] if len(t_single) == 1 else None
    detail["hsrl2_single_outcome"] = h_single[0] if len(h_single) == 1 else None
    if detail["tavern_single_outcome"] and detail["hsrl2_single_outcome"]:
        if detail["tavern_single_outcome"] != detail["hsrl2_single_outcome"]:
            detail["verdict"] = "mismatch"
            detail["mismatch_reason"] = (
                f"deterministic winner: tavern={detail['tavern_single_outcome']} "
                f"hsrl2={detail['hsrl2_single_outcome']}")
            return detail
        w = detail["tavern_single_outcome"]
        if w in ("a", "b"):
            tv = dt[f"{w}_values"]
            hv = dh[f"{w}_values"]
            if tv != hv:
                detail["verdict"] = "mismatch"
                detail["mismatch_reason"] = (
                    f"deterministic damage mismatch: tavern={tv} hsrl2={hv}")
                return detail
        detail["verdict"] = "exact_match"
        return detail
    # 非确定性：分布 + 伤害均值容忍
    if detail["win_rate_max_diff"] > dist_tol:
        detail["verdict"] = "mismatch"
        detail["mismatch_reason"] = (
            f"win rate diff {detail['win_rate_max_diff']:.3f} > {dist_tol}")
        return detail
    for side in ("a", "b"):
        tv, hv = dt[f"{side}_mean"], dh[f"{side}_mean"]
        if tv is not None and hv is not None and abs(tv - hv) > damage_mean_tol:
            detail["verdict"] = "mismatch"
            detail["mismatch_reason"] = (
                f"damage mean mismatch ({side}): tavern={tv} hsrl2={hv}")
            return detail
    detail["verdict"] = "dist_match"
    return detail


def compare_first_attacker(tavern_attackers: List[str],
                           hs_attackers: Dict[str, int],
                           n_hs: int) -> Dict[str, Any]:
    """首攻方比较（约定容忍：双方都随机 = MATCH）。"""
    t_set = set(tavern_attackers)
    h_set = {k for k, v in hs_attackers.items() if v > 0}
    detail = {
        "tavern_attackers": list(tavern_attackers),
        "hsrl2_attacker_counts": dict(hs_attackers),
        "tavern_deterministic": len(t_set) == 1,
        "hsrl2_deterministic": len(h_set) == 1,
    }
    if len(t_set) > 1 and len(h_set) > 1:
        detail["verdict"] = "dist_match"
        detail["note"] = "双方都随机（约定差异容忍）"
    elif t_set == h_set:
        detail["verdict"] = "exact_match"
    else:
        detail["verdict"] = "mismatch"
        detail["mismatch_reason"] = (
            f"first attacker: tavern={sorted(t_set)} hsrl2={sorted(h_set)}")
    return detail


def classify_duel(scenario, detail: Dict[str, Any],
                  first_attacker_detail: Optional[Dict[str, Any]] = None
                  ) -> tuple[str, str]:
    """把 verdict 映射到审计分类。"""
    expected = getattr(scenario, "expected", "MATCH")
    why = getattr(scenario, "why", "")
    unsupported = getattr(scenario, "unsupported_reason", "")
    if unsupported:
        return "UNSUPPORTED", unsupported
    fa_verdict = (first_attacker_detail or {}).get("verdict")
    if fa_verdict == "mismatch":
        if expected == "CONVENTION_DIFF":
            return "CONVENTION_DIFF", (
                why or "first-attacker tie-break is a reference convention "
                       "(no decisive official evidence)")
        return "ENGINE_BUG", (why or "first attacker mismatch")
    if detail.get("tavern_truncated") or detail.get("hsrl2_truncated"):
        if detail.get("hsrl2_errors"):
            return "UNSUPPORTED", f"combat guard: {detail['hsrl2_errors']}"
        return "CONVENTION_DIFF", "simulator truncation guard (safety limit, not a rule)"
    v = detail.get("verdict")
    if v in ("exact_match", "dist_match"):
        return "MATCH", why
    if expected == "DEFERRED":
        return "DEFERRED", (why or detail.get("mismatch_reason")
                            or "deferred: evidence insufficient")
    if expected == "CONVENTION_DIFF":
        # 含两类：(a) RNG/顺序约定；(b) 参照侧实现差异（如 AC-04 的 AT 侧
        # 脚本行为异常——F-35 控制实验证明 hsrl2 与无脚本白板一致）。
        return "CONVENTION_DIFF", (why or detail.get("mismatch_reason")
                                   or "reference-side implementation difference")
    return "ENGINE_BUG", detail.get("mismatch_reason") or (why or "mismatch")


# ══════════════════════════════════════════════════════════════════════
# 经济/流程
# ══════════════════════════════════════════════════════════════════════

def _canon(v: Any) -> Any:
    """把 list/dict 归一成可比较的 canonical 结构（float→round）。"""
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in sorted(v.items())}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def compare_economy(scenario, tavern_probe: Dict[str, Any],
                    hs_probe: Dict[str, Any]) -> Dict[str, Any]:
    diff_fields = []
    for key in scenario.keys:
        tv = _canon(tavern_probe.get(key))
        hv = _canon(hs_probe.get(key))
        if tv != hv:
            diff_fields.append({"key": key, "autotavern": tv, "hsrl2": hv})
    detail = {"keys": list(scenario.keys), "diff_fields": diff_fields,
              "match": not diff_fields}
    if not diff_fields:
        detail["verdict"] = "exact_match"
        classification = "MATCH"
    else:
        detail["verdict"] = "mismatch"
        classification = scenario.expected if scenario.expected in (
            "ENGINE_BUG", "DATA_GAP", "CONVENTION_DIFF") else "ENGINE_BUG"
    return detail, classification


def compare_flow(tavern_obs: Dict[str, Any],
                 hs_obs: Dict[str, Any]) -> Dict[str, Any]:
    """整局流程不变量（两引擎各自验证同一组规则不变量）。"""
    problems = []

    def check(name: str, ok: bool, info: Any) -> None:
        if not ok:
            problems.append({"invariant": name, "info": info})

    # AutoTavern bot 整局
    tg = tavern_obs
    check("tavern_game_over", bool(tg.get("over")), tg)
    pl = list(tg.get("placements") or [])
    check("tavern_placements_permutation",
          sorted(pl) == list(range(1, len(pl) + 1)) and len(set(pl)) == len(pl),
          pl)
    # hsrl2 随机整局
    hg = hs_obs
    check("hsrl2_game_finished_or_capped",
          bool(hg.get("finished")) or int(hg.get("turn") or 0) <= 50, hg)
    check("hsrl2_no_crash", not hg.get("error"), hg)
    detail = {
        "tavern": tavern_obs,
        "hsrl2": hs_obs,
        "problems": problems,
        "verdict": "exact_match" if not problems else "mismatch",
    }
    return detail, ("MATCH" if not problems else "ENGINE_BUG")


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(
            row["classification"], 0) + 1
    return {"total": len(rows), "counts": counts}
