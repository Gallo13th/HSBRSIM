"""结构化价值特征（~40 维）：从 obs features(3227) + cards(124) 计算。"""
from __future__ import annotations
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "rust", "python")):
    if p not in sys.path:
        sys.path.insert(0, p)

import hsbg.env.obs_std as O

_BOARD0, _NB, _MF = 68, 7, 31
_CARDS = None
_CID2ID = None
_RET = None
_KEYWORDS = ["taunt", "divine_shield", "poisonous", "windfury", "reborn", "deathrattle",
             "battlecry", "aoe", "shield", "rally", "spellcraft", "avenge"]


def _init() -> None:
    global _CARDS, _CID2ID, _RET
    if _CARDS is not None:
        return
    import hsbg_engine as E
    d = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("cards") or d.get("data") or list(d.values())
    _CARDS = {str(c["id"]): c for c in d if isinstance(c, dict) and c.get("id")}
    _CID2ID = {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}
    _RET = set()
    for cid, c in _CARDS.items():
        t = int(c.get("tier") or 0)
        tx = str(c.get("text") or "").lower()
        if 4 <= t <= 6 and (cid in ("BG21_015", "BG29_813", "BG36_245", "BG36_640")
                            or "permanently keep" in tx or "double" in tx or "twice" in tx):
            _RET.add(cid)


def rich_feat(features: np.ndarray, cards: np.ndarray) -> np.ndarray:
    """返回 ~40 维特征（顺序固定）。"""
    _init()
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    ca = np.asarray(cards, dtype=np.int64).reshape(-1)
    out = []
    # 基础经济/全局
    turn = float(f[O.GLOBAL_FIELD_INDEX["turn"]]) * 20.0
    gold = float(f[O.GLOBAL_FIELD_INDEX["gold"]]) * 10.0
    tier = float(f[O.GLOBAL_FIELD_INDEX["tier"]]) * 6.0
    upg = float(f[O.GLOBAL_FIELD_INDEX["upgrade_price"]]) * 10.0
    health = float(f[O.GLOBAL_FIELD_INDEX["health"]]) * 40.0
    out += [turn, gold, tier, upg, health]
    # 盘面
    b = f[O.SLICE_BOARD].reshape(_NB, _MF)
    pres = b[:, 0] > 0.5
    atk = b[:, 1] * 10.0
    hp = b[:, 2] * 10.0
    sig = float(np.where(pres, atk + hp, 0.0).sum())
    cnt = int(pres.sum())
    golds = int(np.where(pres, b[:, 5] > 0.5, False).sum())
    # 种族 one-hot 计数（11 位 → 7 大族 + 其他）
    race_bits = (b[:, 20:31] > 0.5) & pres[:, None]
    races = ["BEAST", "MURLOC", "DRAGON", "ELEMENTAL", "MECH", "PIRATE", "UNDEAD", "QUILBOAR",
             "NAGA", "DEMON", "ALL"]
    race_cnt = {r: int(race_bits[:, i].sum()) for i, r in enumerate(races)}
    out += [float(cnt), float(sig), np.log1p(sig)]
    for r in ("BEAST", "MURLOC", "DRAGON", "ELEMENTAL", "MECH", "PIRATE", "UNDEAD", "QUILBOAR"):
        out.append(float(race_cnt.get(r, 0)))
    # 关键词计数（12 位）
    kw_start = int(O.MINION_KEYWORDS)
    kw_bits = (b[:, kw_start:kw_start + 12] > 0.5) & pres[:, None]
    for i in range(12):
        out.append(float(kw_bits[:, i].sum()))
    # 随从 id → tier/golden/retention/buff
    sl = O.CARD_BLOCK_SLICES["card_board"]
    ids = [int(x) - 1 for x in ca[sl.start:sl.stop] if int(x) > 0]
    tiers = []; golden_n = 0; ret_n = 0; buff = 0.0
    for cid in ids:
        sid = _CID2ID.get(cid, "")
        c = _CARDS.get(sid) or (_CARDS.get(sid[:-2]) if sid.endswith("_G") else {}) or {}
        tiers.append(int(c.get("tier") or 0))
        base = _CARDS.get(sid[:-2] if sid.endswith("_G") else sid) or {}
        buff += max(0.0, (atk[len(out) * 0] if False else 0.0))
    golden_n = int(np.where(pres, b[:, 5] > 0.5, False).sum())
    ret_n = sum(1 for cid in ids
                if (_CID2ID.get(cid, "")[:-2] if _CID2ID.get(cid, "").endswith("_G")
                    else _CID2ID.get(cid, "")) in _RET)
    # buff 总量：Σ(实际 − 基础)（按 board 顺序对齐 ids 不可靠时用近似：sig − Σ基础）
    base_sum = 0.0
    for cid in ids:
        sid = _CID2ID.get(cid, "")
        c = _CARDS.get(sid) or _CARDS.get(sid[:-2] if sid.endswith("_G") else sid) or {}
        base_sum += float(int(c.get("atk") or 0) + int(c.get("hp") or 0))
    tb = max(0.0, sig - base_sum)
    t5 = sum(1 for t in tiers if t >= 5)
    t4 = sum(1 for t in tiers if t >= 4)
    # 集中度
    maxmin = float(np.where(pres, atk + hp, 0.0).max()) if cnt else 0.0
    conc = maxmin / max(1.0, sig)
    out += [float(golds), float(ret_n), float(t5), float(t4), np.log1p(tb), float(conc)]
    # 手牌 / 法术
    hsl = O.CARD_BLOCK_SLICES["card_hand"]
    hand_ids = [int(x) - 1 for x in ca[hsl.start:hsl.stop] if int(x) > 0]
    hand_n = len(hand_ids)
    spells = 0
    for cid in hand_ids:
        sid = _CID2ID.get(cid, "")
        c = _CARDS.get(sid) or {}
        if "spell" in str(c.get("type") or "").lower() or "Spell" in str(c.get("card_type") or ""):
            spells += 1
    # 饰品数
    tsl = O.CARD_BLOCK_SLICES["card_trinkets"]
    trinkets = int(sum(1 for x in ca[tsl.start:tsl.stop] if int(x) > 0))
    out += [float(hand_n), float(spells), float(trinkets)]
    return np.asarray(out, dtype=np.float32)


def n_features() -> int:
    return 42
