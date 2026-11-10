#!/usr/bin/env python3
"""通用套路执行器（覆盖全部 31 套）：从 data/comp_plans.json 自动推导
keep / cycle / 受益者，然后在沙盒里按攻略"循环"方式操作。

关键概念（上一次实现缺的就是这三个）：
- keep：必须留场的卡（启动核心 + 收益核心 + 放大器 + 协同件）
- cycle：买→打出（触发收益）→立刻卖掉的一次性触发件
- beneficiary：收益对象（种族或机制），如卡雷苟斯→龙、提图斯→亡语、达卡莱→回合结束
"""
from __future__ import annotations
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python")); sys.path.insert(0, ROOT)
import hsbg_engine as E  # noqa: E402

PLANS = json.load(open(os.path.join(ROOT, "data", "comp_plans.json"), encoding="utf-8"))["plans"]
CAT = {int(c["cid"]): c for c in json.loads(E.catalog_json())}
NAME2ID: dict[str, list[tuple[int, str]]] = {}
for cid, c in CAT.items():
    if c.get("name_zh"):
        NAME2ID.setdefault(c["name_zh"], []).append((cid, c.get("id")))
POOL = {cid for cid, c in CAT.items() if c.get("in_pool")}

# 放大器 → 受益机制
AMP_MECH = {"提图斯·瑞文戴尔": "亡语", "达卡莱附魔师": "回合结束", "布莱恩·铜须": "战吼"}
# 特殊卡 → 受益种族（攻略明确写的）
CARD_RACE = {"奥术守护者卡雷苟斯": "DRAGON", "执念诗心龙": "DRAGON", "英勇的巢母": "DRAGON",
             "红衣纳迪娜": "DRAGON", "赤红守备巨龙": "DRAGON", "龙族看护员": "DRAGON"}
# 种族名（中文）→ catalog races 里的标签
RACE_TAG = {"龙": "DRAGON", "亡灵": "UNDEAD", "野兽": "BEAST", "机械": "MECHANICAL",
            "鱼人": "MURLOC", "元素": "ELEMENTAL", "恶魔": "DEMON", "野猪人": "QUILBOAR",
            "海盗": "PIRATE", "纳迦": "NAGA", "畸变怪": "ABERRATION"}


def resolve(name: str):
    for cid, _sid in NAME2ID.get(name, []):
        if cid in POOL:
            return cid
    return None


def nm(cid: int) -> str:
    return (CAT.get(int(cid)) or {}).get("name_zh") or f"#{cid}"


def races(cid: int) -> list[str]:
    return list((CAT.get(int(cid)) or {}).get("races") or [])


def txt(cid: int) -> str:
    return (CAT.get(int(cid)) or {}).get("text_zh") or ""


def mech(cid: int) -> set[str]:
    t = txt(cid)
    out = set()
    if "亡语" in t: out.add("亡语")
    if "战吼" in t: out.add("战吼")
    if "回合结束" in t: out.add("回合结束")
    return out


def build(plan: dict) -> dict:
    """把一套攻略编译成执行参数：keep/cycle/beneficiary/min_count。"""
    ids = {r: {c for c in (resolve(x) for x in (plan.get(r) or [])) if c}
           for r in ("econ", "start", "pay", "amp", "syn", "flex")}
    keep = set(ids["start"]) | set(ids["pay"]) | set(ids["amp"]) | set(ids["syn"])
    # 受益者：先从放大器/特殊卡推，再从阵容名推种族
    target_mech = set()
    for a in plan.get("amp") or []:
        if a in AMP_MECH:
            target_mech.add(AMP_MECH[a])
    # 先看阵容名的种族（#16 鱼人-魔鳍 不能因为带"龙族看护员"就判成龙）
    target_race = None
    head = str(plan["name"]).split("-")[0]      # "野兽-美味龙虾" 的种族只看前缀，避免"龙虾"里的"龙"
    for zh, tag in RACE_TAG.items():
        if zh in head:
            target_race = tag
            break
    if target_race is None:
        for c in sorted(keep):
            if nm(c) in CARD_RACE and c in ids["start"]:
                target_race = CARD_RACE[nm(c)]
                break
    # 机制收益 vs 种族收益：若两者互斥（如"亡灵-攻击力成长"的提图斯只放大亡语），
    # 保留二者，执行时按"任一条满足即算受益"计算
    # keep 里与受益者无关的卡 → 降级为 cycle（例如元素堆里的非龙卡）
    def relevant(cid: int) -> bool:
        if target_race and target_race in races(cid):
            return True
        if target_mech and (target_mech & mech(cid)):
            return True
        if cid in ids["amp"] or cid in ids["start"] or cid in ids["pay"]:
            return True
        return False
    keep = {c for c in keep if relevant(c)}
    cycle = set(ids["syn"]) - keep | set(ids["flex"])
    if target_mech:      # 机制受益：任何具备该机制的卡都可作为循环件
        cycle |= {cid for cid in POOL if target_mech & mech(cid)} - keep
    if target_race:      # 种族受益：非受益种族的卡不进 keep
        cycle |= {cid for cid in ids["syn"] if target_race not in races(cid)} - keep
    return dict(plan=plan, ids=ids, keep=keep, cycle=cycle,
                target_race=target_race, target_mech=target_mech,
                min_beneficiaries=int(plan.get("min_count") or 4))


ALL = {p["id"]: build(p) for p in PLANS}
if __name__ == "__main__":
    for pid, b in ALL.items():
        print("%s %-18s keep=%2d cycle=%3d 受益=%s%s" % (
            pid, b["plan"]["name"], len(b["keep"]), len(b["cycle"]),
            b["target_race"] or "", "/".join(sorted(b["target_mech"]))))
