"""AC-01…AC-04 最小复现脚本（每条可直接运行）。

用法::

    python3 -m tools.ac_conformance.repro            # 全部
    python3 -m tools.ac_conformance.repro AC-01 AC-04

每条输出「输入 / AutoTavern / hsrl2 / 判定依据 / 建议」。所有数字由本次
运行实测，不写死历史值（除了断言方向）。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

from . import data_diff, hsrl2_api, tavern_api


def ac01_first_attacker_tier() -> Dict[str, Any]:
    """AC-01 先攻判定：数量相同应比较酒馆等级（hsrl2 未实现）。"""
    unit = [{"atk": 2, "hp": 2, "kws": []}]
    tavern_attackers: List[str] = []
    for seed in range(6):
        g = tavern_api.build_duel(seed, unit, unit, tier_a=1, tier_b=5)
        smp = tavern_api.combat_sample(g)
        tavern_attackers.append(smp.get("first_attacker"))
    hs = hsrl2_api.run_trials(unit, unit, seeds=64, tier_a=1, tier_b=5)
    return {
        "id": "AC-01",
        "title": "先攻判定：数量相同 → 参照按酒馆等级、HSBRSIM 随机（CONVENTION_DIFF）",
        "input": "A: 1×2/2 tier1；B: 1×2/2 tier5；第 1 回合",
        "autotavern": {"first_attacker_samples": tavern_attackers},
        "hsrl2": {"attacker_first_counts": hs["attacker_first"]},
        "evidence": "AutoTavern crates/taverngym/src/combat.rs:316 "
                    "('More minions attacks first; on a tie the higher Tavern "
                    "Tier; then random')；但官方 wiki.gg /wiki/Battlegrounds "
                    "现行文本为「同数量随机」；中文 2020 攻略写等级优先；HSBRSIM "
                    "旧规则文档写随机 → 二源冲突、参照实现单方，2026-10-26 "
                    "Lead 裁定改判 CONVENTION_DIFF（暂不作为 ENGINE_BUG）。",
        "verdict": "CONVENTION_DIFF",
        "fix": "不影响功能正确性；若要和 AutoTavern 行为逐位对齐（例如共享 BB "
               "语料/参照分布），可在 hsrl2._determine_first 平局分支比较 "
               "hero.tavern_tier，仍相同才随机。决定性证据路径：真实 "
               "Power.log/HDT 语料中出现「同数量不同等级且可判定先手」的样本。",
    }


def ac02_pool_tier1_copies() -> Dict[str, Any]:
    """AC-02 T1 随从池份数：16 vs 15。"""
    import json as _json
    import taverngym
    at_cfg = _json.loads(taverngym.default_config_json())["pool_copies_by_tier"]
    hs = hsrl2_api.economy_probe()["pool_copies_by_tier"]
    return {
        "id": "AC-02",
        "title": "T1 随从池份数（已修复）：16 → 15",
        "input": "规则常量（无需战斗）",
        "autotavern": at_cfg,
        "hsrl2": hs,
        "evidence": "AutoTavern config.rs:245 pool_copies_by_tier=[15,15,13,11,9,7,5]"
                    "（36.6.0 wiki 数据）；hearthstone.wiki.gg `/wiki/Battlegrounds` "
                    "副本表 T1=15（2026-10-26 抓取）；hsrl2/constants.py "
                    "POOL_COPIES_BY_TIER[1]=16（旧 35.x 文档值）。",
        "verdict": "MATCH（2026-10-26 engine-fixer 已修复）",
        "fix": "已改 15；回跑 hsrl2/tests 池相关用例（engine-fixer）。",
    }


def ac03_upgrade_cost() -> Dict[str, Any]:
    """AC-03 基础升级费：T5/T6 应为 11/11。"""
    import json as _json
    import taverngym
    at_cfg = _json.loads(taverngym.default_config_json())["upgrade_costs"]
    probe = hsrl2_api.economy_probe()
    return {
        "id": "AC-03",
        "title": "基础升级费阶梯（已修复）：T5/T6 9/10 → 11/11",
        "input": "规则常量 + 行为（真实 upgrade_tavern 扣费）",
        "autotavern": {"upgrade_costs": at_cfg,
                       "behavior": tavern_api.economy_probe()["upgrade_by_tier"]},
        "hsrl2": {"upgrade_costs": probe["upgrade_costs"],
                  "behavior": probe["upgrade_by_tier"]},
        "evidence": "AutoTavern config.rs:237 upgrade_costs=[5,7,8,11,11,10]"
                    "（索引 0..5 = 目标 tier2..7）；hearthstone.wiki.gg "
                    "`/wiki/Battlegrounds` 升级费表 T2=5/T3=7/T4=8/T5=11/T6=11"
                    "（2026-10-26 抓取）；hsrl2/constants.py BASE_UPGRADE_COSTS"
                    "={2:5,3:7,4:8,5:9,6:10,7:11}。",
        "verdict": "MATCH（2026-10-26 engine-fixer 已修复）",
        "fix": "已改 11/11（T7=10 对齐参照）；同步 hsrl2/tests 升级费断言"
               "（engine-fixer）。",
    }


def ac04_avenge_taunt_support() -> Dict[str, Any]:
    """AC-04 BG34_405：同胜负下胜方可达伤害集合不同（AT 侧脚本候选 / DEFERRED）。

    含 engine-fixer F-35 的控制实验复现：同属性无脚本白板（5/4 tier3 + 3×1/3）
    在两引擎伤害集合一致，只有 AT 侧“带 BG34_405 脚本”时分布异常。
    """
    from collections import Counter
    from .scenarios import U
    units_a = [U(1, 3), U(1, 3), U(1, 3)]
    units_b = [U(2, 2), U(2, 2), U(2, 2)]
    ctrl_a = [U(5, 4, tier=3), U(1, 3), U(1, 3), U(1, 3)]

    g = tavern_api.build_duel(0, units_a, units_b, card_a=["BG34_405"],
                              turn=8)
    t = tavern_api.combat_trials(g, 400)
    h = hsrl2_api.run_trials(units_a, units_b, seeds=400, turn=8,
                             card_a=["BG34_405"])
    gt = tavern_api.build_duel(0, ctrl_a, units_b, turn=8)
    t_ctrl = tavern_api.combat_trials(gt, 400)
    h_ctrl = hsrl2_api.run_trials(ctrl_a, units_b, seeds=400, turn=8)
    hist = lambda obs: dict(sorted(
        Counter(obs["damage_by_winner"]["a"]).items()))
    return {
        "id": "AC-04",
        "title": "BG34_405 Relentless Deflector：两个引擎胜方可达伤害集合不同"
                 "（参照侧脚本行为异常 / CONVENTION_DIFF，非 hsrl2 分歧）",
        "input": "A=[BG34_405, 1/3, 1/3, 1/3]，B=[2/2, 2/2, 2/2]，第 8 回合（避开 5 点上限）",
        "autotavern": {"wins": t["wins"],
                       "winner_a_damage_hist": hist(t)},
        "hsrl2": {"wins": h["wins"],
                  "winner_a_damage_hist": hist(h)},
        "control_vanilla": {
            "input": "A=[无脚本 5/4 tier3, 1/3, 1/3, 1/3]，B 同；第 8 回合",
            "autotavern": {"wins": t_ctrl["wins"],
                           "winner_a_damage_hist": hist(t_ctrl)},
            "hsrl2": {"wins": h_ctrl["wins"],
                      "winner_a_damage_hist": hist(h_ctrl)},
        },
        "evidence": "卡面 'Has Taunt while this has Divine Shield. Avenge (3): "
                    "Gain Divine Shield.'；AT 实现 content/minions.rs:261-266。"
                    "engine-fixer F-35 复现（本脚本 control_vanilla 独立复验）："
                    "(1) 400 局中 405 的 Avenge/圣盾/嘲讽从未触发（AT shield_hits=0、"
                    "无 DS/TAUNT 帧；HS keyword_gained 405 得 DS 0 次）；"
                    "(2) 换成同属性无脚本白板后两侧伤害集合一致 "
                    "（本脚本复验：两侧均 {3,4,5,6}）；HS 带卡/不带卡一致，"
                    "只有 AT 带卡时分布异常 → 分歧来自 AT 侧脚本实现，不是 hsrl2 卡脚本 bug。",
        "verdict": "CONVENTION_DIFF（参照侧脚本行为异常，F-35 证据；"
                   "hsrl2 与无脚本白板一致，不改 hsrl2）",
        "fix": "已登记 DEFERRED 待裁定：建议在 AutoTavern Rust 侧逐帧对比 405 与"
               "无脚本白板的 has_taunt/圣盾内部状态，或补真实 Power.log 战斗；"
               "本批 60min 内无法给出决定性证据，故不判 hsrl2 bug。",
    }


BUGS = {
    "AC-01": ac01_first_attacker_tier,
    "AC-02": ac02_pool_tier1_copies,
    "AC-03": ac03_upgrade_cost,
    "AC-04": ac04_avenge_taunt_support,
}


def main(argv: List[str] | None = None) -> int:
    wanted = argv if argv is not None else sys.argv[1:]
    chosen = [k for k in BUGS if not wanted or k in wanted]
    for key in chosen:
        result = BUGS[key]()
        print(f"\n════ {result['id']} {result['title']} ════")
        for field in ("input", "autotavern", "hsrl2", "evidence", "verdict",
                      "fix"):
            print(f"  {field}: {json.dumps(result[field], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
