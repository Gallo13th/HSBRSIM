#!/usr/bin/env python3
"""从 `HSBG.md`（31 套阵容攻略）抽出**依赖复利**的阵容 → 核心卡 id 表。

产物 `data/comp_cards.json`：
    {
      "comps": [{"id": "01", "name": "机械-手速磁力", "tier": "S", "compounding": true,
                 "core": ["极性B-Box拳手", ...], "core_ids": [111, ...]}],
      "bias": {"MULT": {name: [ids]}, "GROW": {...}, "ENGINE": {...}, "ECON": {...}},
      "bias_ids": [id, ...]      # 默认 bias 集合 = MULT ∪ GROW ∪ ENGINE
    }

分类（用于 buy bias 的强度分级）：
    MULT   —— 乘算放大器（布莱恩·铜须/达卡莱附魔师/提图斯·瑞文戴尔），1 张即翻倍
    GROW   —— 成长引擎（巴琳达/邪能野猪人/永恒骑士/执念诗心龙…），自身随时间线性成长
    ENGINE —— 触发次数/经济/生成器（罗杰斯以外：起床号/火花破坏机/猎头狮鹫…）
    ECON   —— 纯经济（罗杰斯/私掠者/上进的逃兵/魔鳍真菌学家/酒馆旋风）
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
import hsbg_engine as E  # noqa: E402

#: 阵营分类（人工整理，来自 HSBG.md 的"核心/附加/操作顺序"，只保留与复利相关的）
CAT = {
    # 乘算放大器
    "布莱恩·铜须": "MULT", "达卡莱附魔师": "MULT", "提图斯·瑞文戴尔": "MULT",
    # 自身成长/吞噬/宝石/亡语成长引擎
    "巴琳达·斯通赫尔斯": "GROW", "邪能野猪人": "GROW", "恶魔干扰者": "GROW",
    "永恒骑士": "GROW", "永恒召唤者": "GROW", "永恒大亨": "GROW",
    "执念诗心龙": "GROW", "灰烬腐蚀者": "GROW", "活化艾泽里特": "GROW",
    "时尚魅影": "GROW", "断手被遗忘者": "GROW", "猎头狮鹫": "GROW",
    "逐亡陆行鸟": "GROW", "香蕉猛猿": "GROW", "多面辅助无人机": "GROW",
    "转运构筑机": "GROW", "小瞎眼": "GROW", "魔鳍学徒": "GROW",
    "热气球测绘员": "GROW", "守门融合怪": "GROW", "剃刀沼泽舞扇者": "GROW",
    "堑壕斗士": "GROW", "牺牲的愤怒卫士": "GROW", "巨狼戈德林": "GROW",
    "希望信使": "GROW", "奥术守护者卡雷苟斯": "GROW", "木乃伊工匠": "GROW",
    "丧钟死灵": "GROW", "德鲁斯特堕落屠夫": "GROW", "萨满招潮者": "GROW",
    "合唱鱼人": "GROW", "赤红守备巨龙": "GROW", "青铜时光行者": "GROW",
    "符文奥术师": "GROW", "英勇的巢母": "GROW", "红衣纳迪娜": "GROW",
    "龙族看护员": "GROW", "深潜巨兽": "GROW", "暴虐巨蝎": "GROW",
    "绿松石飞掠虫": "GROW", "下水道老鼠头目": "GROW", "疑之影": "GROW",
    "惧之煞": "GROW", "无羁雷暴": "GROW", "空气亡魂": "GROW",
    "无面转化者": "GROW", "梦魇侵蚀怪": "GROW", "神秘的克熙尔": "GROW",
    "健身搏猪": "ENGINE", "鲜血精研者": "ENGINE", "极速野猪骑士": "ENGINE",
    "得胜的地卜术师": "ENGINE", "自动起床号": "ENGINE", "火花破坏机": "ENGINE",
    "极性B-Box拳手": "ENGINE", "复映无人机": "ENGINE", "海藻护卫": "ENGINE",
    "魔网浮灵": "ENGINE", "艾瑞达逃脱大师": "ENGINE", "邪火咒龙": "ENGINE",
    "黑暗傀儡师": "ENGINE", "天诞逃生飞龙": "ENGINE", "美味龙虾": "ENGINE",
    "魔焰执行者": "UTIL", "莽神火车王": "UTIL", "黑客鱼人": "UTIL",
    "怒胆喷毒鱼人": "UTIL", "下水道逃生鱼人": "UTIL", "凶饿的觅食者": "UTIL",
    "空军上将罗杰斯": "ECON", "骄傲的私掠者": "ECON", "上进的逃兵": "ECON",
    "魔鳍真菌学家": "ECON", "酒馆旋风": "ECON",
}

#: 复利阵容（编号, 名称, 评级, 核心卡）—— 直接来自 HSBG.md 的 31 套里"靠成长/乘算"的那些
COMPS = [
    ("01", "机械-手速磁力", "S", ["极性B-Box拳手", "空军上将罗杰斯", "骄傲的私掠者", "自动起床号", "火花破坏机", "复映无人机", "上进的逃兵", "布莱恩·铜须"]),
    ("02", "野猪人-手速酒馆强化", "S", ["邪能野猪人", "巴琳达·斯通赫尔斯", "布莱恩·铜须", "热气球测绘员", "扭曲的愤怒卫士", "得胜的地卜术师", "守门融合怪", "恶魔干扰者"]),
    ("03", "喝茶流", "S", ["热气球测绘员", "巴琳达·斯通赫尔斯", "守门融合怪", "布莱恩·铜须", "黑暗傀儡师"]),
    ("04", "元素-活化艾泽里特", "S", ["活化艾泽里特", "魔网浮灵", "巴琳达·斯通赫尔斯", "海藻护卫", "布莱恩·铜须"]),
    ("05", "恶魔-自伤", "S", ["灰烬腐蚀者", "巴琳达·斯通赫尔斯", "艾瑞达逃脱大师", "恶魔干扰者", "布莱恩·铜须"]),
    ("06", "亡灵-手速亡灵", "S", ["断手被遗忘者", "空军上将罗杰斯", "骄傲的私掠者", "被遗忘者纺织工", "时尚魅影"]),
    ("07", "鱼人-关键词", "S", ["黑客鱼人", "怒胆喷毒鱼人", "下水道逃生鱼人", "海藻护卫", "布莱恩·铜须"]),
    ("08", "亡灵-攻击力成长", "A", ["断手被遗忘者", "木乃伊工匠", "德鲁斯特堕落屠夫", "丧钟死灵", "时尚魅影", "永恒召唤者", "提图斯·瑞文戴尔"]),
    ("10", "恶魔-酒馆强化", "A", ["邪能野猪人", "巴琳达·斯通赫尔斯", "鬼影幻术师", "恶魔干扰者"]),
    ("13", "恶魔-亡语/酒馆强化", "A", ["提图斯·瑞文戴尔", "牺牲的愤怒卫士", "鬼影幻术师"]),
    ("16", "鱼人-魔鳍", "A", ["小瞎眼", "达卡莱附魔师", "邪火咒龙", "魔鳍学徒", "魔鳍真菌学家", "布莱恩·铜须"]),
    ("22", "野猪人-宝石弹幕", "A", ["剃刀沼泽舞扇者", "堑壕斗士", "提图斯·瑞文戴尔", "达卡莱附魔师", "邪能野猪人"]),
    ("24", "龙-希望信使", "B", ["执念诗心龙", "希望信使", "英勇的巢母", "红衣纳迪娜"]),
    ("25", "亡灵-永恒骑士", "B", ["永恒骑士", "永恒召唤者", "永恒大亨"]),
    ("26", "畸变怪-腐泥", "B", ["达卡莱附魔师", "邪火咒龙", "黑暗傀儡师", "梦魇侵蚀怪", "神秘的克熙尔"]),
    ("27", "龙-法术强度", "B", ["执念诗心龙", "赤红守备巨龙", "青铜时光行者", "天诞逃生飞龙", "符文奥术师", "布莱恩·铜须"]),
    ("28", "机械-扩音机", "B", ["多面辅助无人机", "达卡莱附魔师", "转运构筑机", "机智的机器人"]),
    ("29", "鱼人-招潮者", "B", ["合唱鱼人", "凶饿的觅食者", "魔鳍真菌学家", "巴琳达·斯通赫尔斯", "萨满招潮者", "布莱恩·铜须"]),
    ("30", "龙-战吼", "B", ["执念诗心龙", "龙族看护员", "海藻护卫", "英勇的巢母", "布莱恩·铜须", "奥术守护者卡雷苟斯"]),
    ("31", "野兽-召唤", "B", ["提图斯·瑞文戴尔", "香蕉猛猿", "下水道老鼠头目", "猎头狮鹫", "逐亡陆行鸟", "巨狼戈德林"]),
]


def name_to_ids() -> dict:
    out: dict = {}
    for i in range(0, int(E.N_CARDS)):
        try:
            info = E.card_info(i)
        except Exception:  # noqa: BLE001
            continue
        if not info:
            continue
        for nm in (str(info[1] or ""), str(info[2] or "")):
            if nm:
                out.setdefault(nm, set()).add(int(i))
    return out


def availability(n2i: dict, names, *, seeds: int = 40, cfg_json: str = "") -> dict:
    """统计每张卡在 N 个大厅的卡池里出现的比例（引擎的 pool=universe 按大厅种族过滤）。

    这一步是必要的：当前规则集的卡池只含**与大厅种族匹配**的随从，无种族的 T5 卡
    （提图斯·瑞文戴尔 / 达卡莱附魔师 / 布莱恩·铜须）其实**从不出现在商店里**——
    B11 前三轮"买放大器"完全空转就是因为它（见 docs/B11_DESIGN.md）。
    """
    sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
    import hsbg_engine as E  # noqa: PLC0415
    try:
        sys.path.insert(0, ROOT)
        from hsbg.az.train.game_rules import game_config_json  # noqa: PLC0415
        cfg = game_config_json()
    except Exception:  # noqa: BLE001
        cfg = cfg_json or "{}"
    unis = []
    for seed in range(1, int(seeds) + 1):
        try:
            st = json.loads(E.Game(seed, cfg).state_json())
        except Exception:  # noqa: BLE001
            continue
        unis.append(set(int(x) for x in (st.get("universe") or [])))
    out = {}
    for nm in names:
        ids = n2i.get(nm) or []
        if not ids or not unis:
            out[nm] = 0.0
            continue
        hit = sum(1 for u in unis if any(i in u for i in ids))
        out[nm] = hit / len(unis)
    return out


def main() -> int:
    n2i = name_to_ids()
    comps, missing = [], []
    for cid, name, tier, core in COMPS:
        ids, cores_ok = [], []
        for nm in core:
            got = sorted(n2i.get(nm) or [])
            if got:
                ids.extend(got)
                cores_ok.append(nm)
            else:
                missing.append((cid, nm))
        comps.append({"id": cid, "name": name, "tier": tier, "compounding": True,
                      "core": cores_ok, "core_ids": sorted(set(ids))})
    bias: dict = {}
    for nm, cat in CAT.items():
        ids = sorted(n2i.get(nm) or [])
        if ids:
            bias.setdefault(cat, {})[nm] = ids
    avail = availability(n2i, list(CAT.keys()))
    # 只有"在当前规则集的卡池里真的会出现"的卡才值得作为买卡目标（avail>=0.4）
    bias_avail: dict = {}
    for nm, cat in CAT.items():
        ids = sorted(n2i.get(nm) or [])
        if ids and avail.get(nm, 0.0) >= 0.4:
            bias_avail.setdefault(cat, {})[nm] = ids
    bias_eff = bias_avail
    bias_ids = sorted({i for cat in ("MULT", "GROW", "ENGINE")
                       for v in (bias_eff.get(cat) or {}).values() for i in v})
    spec = {
        "source": "HSBG.md（31 套阵容攻略）",
        "availability_note": "avail = 该卡在 40 个大厅卡池里出现的比例；bias 只保留 avail>=0.4 的卡，"
                             "因为当前规则集的卡池按大厅种族过滤（无种族 T5 卡从不出现在商店）",
        "avail": {k: round(v, 3) for k, v in sorted(avail.items(), key=lambda kv: -kv[1])},
        "note": "只收录依赖复利（乘算放大器 / 自身成长 / 触发引擎）的阵容；分级见 CAT",
        "comps": comps,
        "bias": bias,                       # 全量（含当前卡池里没有的卡，供将来换规则集）
        "bias_available": bias_eff,         # 只用"确实会出现"的卡
        "bias_ids": bias_ids,
        "mult_ids": sorted({i for v in (bias_eff.get("MULT") or {}).values() for i in v}),
        "grow_ids": sorted({i for v in (bias_eff.get("GROW") or {}).values() for i in v}),
        "engine_ids": sorted({i for v in (bias_eff.get("ENGINE") or {}).values() for i in v}),
        "econ_ids": sorted({i for v in (bias_eff.get("ECON") or {}).values() for i in v}),
    }
    out = os.path.join(ROOT, "data", "comp_cards.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    print("[comp] 写出 %s" % out)
    print("[comp] 可用性：>=40%% 的卡 %d / %d；MULT 可用 %d 张" % (
        sum(1 for v in avail.values() if v >= 0.4), len(avail),
        len((bias_eff.get("MULT") or {}))))
    print("[comp] 复利阵容 %d 套；MULT %d 张 / GROW %d 张 / ENGINE %d 张 / ECON %d 张；bias 合计 %d 张"
          % (len(comps), len(spec["mult_ids"]), len(spec["grow_ids"]),
             len(spec["engine_ids"]), len(spec["econ_ids"]), len(bias_ids)))
    if missing:
        print("[comp] 未匹配卡名 %d 个: %s" % (len(missing), missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
