#!/usr/bin/env python3
"""閾炬潯婕忔枟瀹¤锛堢函 CPU锛屼笉璁粌銆佷笉璧峰紩鎿庯級锛氫粠鏃㈡湁 quality_monitor JSON 鎶芥紡鏂楀悇闃躲€?
鐢ㄦ硶:
  python /tmp/s22/funnel_audit.py
浜у嚭:
  runs/az_entity_s23b/funnel.json
  docs/CHAIN_FUNNEL.md
"""
import json
import os
from typing import Any, Dict

ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"
PANELS = {
    "bot_env": "runs/az_entity_s23b/eval/quality_final_bot.json",
    "p09_5seat": "runs/az_entity_s23b/eval/quality_final_p09.json",
    # 10M 鐐瑰仛瀵圭収锛堢湅 10M鈫?0.6M 鐨勫彉鍖栨柟鍚戯級
    "bot_env_10m": "runs/az_entity_s23b/eval/quality_10m_bot.json",
    "p09_5seat_10m": "runs/az_entity_s23b/eval/quality_10m_p09.json",
}


def _pct(x: Any) -> Any:
    return None if x is None else round(100.0 * float(x), 1)


def extract(path: str) -> Dict[str, Any]:
    d = json.load(open(os.path.join(ROOT, path), encoding="utf-8"))
    bt = {int(b["turn"]): b for b in d.get("by_turn", [])}
    s = d.get("infer_search") or {}
    out: Dict[str, Any] = {
        "path": path,
        "games": d.get("games"),
        "mean_rank": round(float(d.get("mean_rank") or 0), 3),
        "top4_pct": _pct(d.get("top4")),
        "win_pct": _pct(d.get("win")),
        "placements": d.get("placements"),
        "death_turn_p50": d.get("death_turn_p50"),
        "death_turn_hist": d.get("death_turn_hist"),
        "death_strength_p50": d.get("death_strength_p50"),
        "survive_t12_pct": _pct(d.get("survive_t12_ratio")),
        # ---- 婕忔枟鍚勯樁 ----
        "rung1_tier_ge4_pct": _pct(d.get("tier_ge4_ratio")),
        "rung1b_tier_ge4_turn_pct": _pct(d.get("tier_ge4_turn_ratio")),
        "rung2_max_tier_p50": d.get("max_tier_p50"),
        "rung2_tier_p50_t15": d.get("tier_p50_t15"),
        "rung2_tier_ge5_t12_pct": _pct(d.get("tier_ge5_t12")),
        "rung2_tier_ge5_t15_pct": _pct(d.get("tier_ge5_t15")),
        "rung3_carrier_shop_offer_pct": _pct(d.get("carrier_shop_offer_rate")),
        "rung3_carrier_encounter_pct": _pct(d.get("carrier_encounter_rate")),
        "rung4_casts_on_carrier_mean": d.get("casts_on_carrier_mean"),
        "rung4_casts_given_carrier": d.get("casts_on_carrier_mean_given_carrier"),
        "rung5_r_carrier_turns_str12": d.get("r_carrier_turns_str12"),
        "rung5_r_ci95": d.get("r_carrier_turns_str12_ci95"),
        "carrier_turns_mean": d.get("carrier_turns_mean"),
        "str12_p50": d.get("str12_p50"),
        "S12": s.get("strength_t12_p50"),
        "S15": s.get("strength_t15_p50"),
        "strength_ratio_t9": round(float(d.get("strength_ratio_t9") or 0), 3),
        "strength_ratio_t12": round(float(d.get("strength_ratio_t12") or 0), 3),
        "strength_ratio_t15": round(float(d.get("strength_ratio_t15") or 0), 3),
        "by_turn": {
            str(t): {
                "n": bt[t].get("n"),
                "tier_p50": bt[t].get("tier_p50"),
                "tier_ge5_pct": _pct(bt[t].get("tier_ge5_ratio")),
                "tier_ge6_pct": _pct(bt[t].get("tier_ge6_ratio")),
                "gold_p50": bt[t].get("gold_p50"),
                "ours_p50": bt[t].get("ours_p50"),
                "real_p50": bt[t].get("real_p50"),
                "ratio_p50": None if bt[t].get("ratio_p50") is None else round(float(bt[t]["ratio_p50"]), 3),
            }
            for t in sorted(bt)
        },
    }
    return out


def gold_tier_table(panel: Dict[str, Any], t_lo: int = 8, t_hi: int = 13) -> list:
    rows = []
    prev_tier = None
    for t in range(t_lo, t_hi + 1):
        b = panel["by_turn"].get(str(t))
        if not b:
            continue
        tier = b.get("tier_p50")
        dtier = None if (prev_tier is None or tier is None) else round(float(tier) - float(prev_tier), 2)
        rows.append({"turn": t, "gold_p50": b.get("gold_p50"), "tier_p50": tier,
                     "delta_tier": dtier, "tier_ge5_pct": b.get("tier_ge5_pct"),
                     "ours_p50": b.get("ours_p50"), "real_p50": b.get("real_p50"),
                     "ratio_p50": b.get("ratio_p50")})
        prev_tier = tier
    return rows


def main() -> None:
    panels = {k: extract(v) for k, v in PANELS.items() if os.path.isfile(os.path.join(ROOT, v))}
    out = {"panels": panels,
           "gold_tier": {k: gold_tier_table(v) for k, v in panels.items()},
           "not_instrumented": [
               "amp 鍙拱(鍟嗗簵鍑虹幇): quality_monitor 涓嶈褰?per-game 鍟嗗簵鍐呭 鈬?鍙兘缁?carrier_shop_offer_rate 浠ｇ悊",
               "amp 涔板埌 / amp 涓婂満 / amp 瑙﹀彂娆℃暟: 鏈惤鐩橈紙闇€瑕佷笓闂?rollout 閲囬泦鍣級",
               "閫愬眬 tier/gold 鏇茬嚎: 鍙瓨浜?by_turn 鑱氬悎锛坧50锛夛紝娌℃湁 per-game 搴忓垪",
           ]}
    os.makedirs(os.path.join(ROOT, "runs/az_entity_s23b"), exist_ok=True)
    with open(os.path.join(ROOT, "runs/az_entity_s23b/funnel.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: {kk: v[kk] for kk in ("mean_rank", "survive_t12_pct", "rung1_tier_ge4_pct",
                                               "rung2_tier_ge5_t15_pct", "rung3_carrier_shop_offer_pct",
                                               "rung4_casts_on_carrier_mean", "S12", "S15")}
                      for k, v in panels.items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
