#!/usr/bin/env python3
"""经典阵容脚本引擎（comp scripts）：核心卡 + 载体 + 类型多样，纯 CPU 全对局实测。

设计（见 docs/COMP_SCRIPTS.md）
------------------------------
1. 每套阵容 = ``核心卡``（buff 源头 / 放大器）+ ``载体``（buff 承受者）+ ``类型要求``。
2. 载体**只吃 buff 不产 buff**；buff 只打载体（或打 ``cast_on`` 指定的放大器），**不给核心**。
3. 其他随从 **tier 无关**，只要求类型不同（「每个类型一个随从」类效果按类型数放大）。
4. 触发条件：**进入**（t≤7 商店/手牌出现核心）、**坚持**（核心齐 + 载体在场且吃完 N 次 buff）、
   **退出**（t≥10 仍缺核心 → 通用铺场：按曲线升本 + 买最大身材）。
5. 六条动作优先级：① 商店有核心就买（刷新 ≤4）② 核心齐 → 所有法术/buff 只打载体
   ③ 优先买未拥有的种族类型 ④ 满场卖「无类型 / 无 buff 价值」者 ⑤ 无动作则刷新 ⑥ 按曲线升本。

用法::

    PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    $PY scripts/comp_scripts.py --list
    $PY scripts/comp_scripts.py --comp A,B --games 30 --workers 12 \
        --configs bot,human --json-out runs/comp_scripts/A.json
    $PY scripts/comp_scripts.py --comp BOT --games 30 --configs bot   # 基线
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import hsbg_engine as E  # noqa: E402
from hsbg.az import env_api as EA  # noqa: E402
from hsbg.az.train.common import mask_from_bytes  # noqa: E402

# ── 动作布局（rust/crates/hsbg-engine/src/actions.rs）───────────────────────
A_END, A_REFRESH, A_FREEZE, A_UPGRADE, A_HERO_POWER = 0, 1, 2, 3, 4
A_DARK_GIFT, A_CANCEL, A_BUY, A_SELL, A_ACTIVATE = 6, 7, 8, 16, 23
A_CHOOSE, A_PLAY, A_MAGNETIZE, A_MOVE = 30, 46, 126, 196
N_CHOICE, N_SHOP, N_POS, N_BOARD, N_HAND = 16, 8, 8, 7, 10

BUY_R = range(A_BUY, A_BUY + N_SHOP)
SELL_R = range(A_SELL, A_SELL + N_BOARD)
PLAY_R = range(A_PLAY, A_PLAY + N_HAND * N_POS)

TRIBES = ("BEAST", "MECHANICAL", "UNDEAD", "DEMON", "PIRATE", "DRAGON",
          "ELEMENTAL", "MURLOC", "QUILBOAR", "NAGA", "ABERRATION")
TRIBE_ZH = {"BEAST": "野兽", "MECHANICAL": "机械", "UNDEAD": "亡灵", "DEMON": "恶魔",
            "PIRATE": "海盗", "DRAGON": "龙", "ELEMENTAL": "元素", "MURLOC": "鱼人",
            "QUILBOAR": "野猪人", "NAGA": "纳迦", "ABERRATION": "异变体", "ALL": "全类型",
            None: "无"}

#: 每级 tier 的最早回合（经济可行性；早于它不升本）
EARLIEST_TIER = {1: 1, 2: 3, 3: 5, 4: 6, 5: 8, 6: 10}


# ── 卡表 ───────────────────────────────────────────────────────────────────
def _catalog() -> Dict[str, dict]:
    return {c["id"]: c for c in json.loads(E.catalog_json())}


CATALOG = _catalog()
GOLDEN_OF: Dict[str, str] = {i: str(c["golden_id"]) for i, c in CATALOG.items()
                             if c.get("golden_id")}


def expand(ids: Iterable[str]) -> set:
    """普通 id → {普通, 金色}（棋盘上的金色随从用 `_G` id）。"""
    out: set = set()
    for i in ids:
        i = str(i)
        out.add(i)
        if i in GOLDEN_OF:
            out.add(GOLDEN_OF[i])
        if i.endswith("_G") and i[:-2] in CATALOG:
            out.add(i[:-2])
    return out


def tier_of(cid: str) -> int:
    return int((CATALOG.get(cid) or {}).get("tier") or 0)


# ── 阵容规格 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CompSpec:
    key: str
    name: str
    archetype: str
    tribe: str
    core: Tuple[str, ...]          # 必买核心（按优先级）
    carrier: Tuple[str, ...]       # 载体：buff 承受者（永不卖）
    cast_on: Tuple[str, ...]       # 法术落点（默认 = carrier；B/C 是放大器）
    type_min: int                  # 场上需要的不同种族数
    trinkets: Tuple[str, ...]
    curve: Tuple[int, ...]         # curve[t-1] = 第 t 回合目标 tier
    spell_heavy: bool = True
    tavern_buy: bool = False       # 买「酒馆里被养最肥」的随从（而不是最高 tier）
    note: str = ""
    enabler: Tuple[str, ...] = ()
    filler: Tuple[str, ...] = ()

    @property
    def aim(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(tuple(self.cast_on) + tuple(self.carrier)))


CURVE_FAST = (2, 2, 3, 4, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6)
CURVE_MID = (2, 2, 3, 4, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6)

COMPS: Dict[str, CompSpec] = {}


def _reg(s: CompSpec) -> CompSpec:
    COMPS[s.key] = s
    return s


# A. Firestone rank1「Neutral Tea Set」：巴琳达（法术打随从施放两次）+ 守门融合怪（全类型载体）
_reg(CompSpec(
    "A", "Neutral Tea Set", "neutral_tea_set", "ABERRATION",
    core=("BG35_883", "BG36_640", "BG_LOE_077"),
    carrier=("BG36_640",), cast_on=("BG36_640",),
    type_min=5, trinkets=("BG36_MagicItem_307", "BG36_MagicItem_831",
                          "BG32_MagicItem_808", "BG32_MagicItem_808t"),
    curve=CURVE_FAST,
    note="法术只打守门融合怪 → 每张法术吐 Misplaced Tea Set（每种类型 +4/+4），巴琳达再翻倍"))

# B. rank12「Quilboar Felboar Spam」：恶魔干扰者（放大器，酒馆 +1/+2 this game）+ 邪能野猪人（载体）
_reg(CompSpec(
    "B", "Quilboar Felboar Spam", "quilboar_felboar_spam", "QUILBOAR",
    core=("BG36_762", "BG28_633", "BG35_883"),
    carrier=("BG28_633",), cast_on=("BG36_762",),
    type_min=4, trinkets=("BG32_MagicItem_808", "BG32_MagicItem_808t",
                          "BG30_MagicItem_442", "BG30_MagicItem_943"),
    curve=CURVE_FAST, tavern_buy=True,
    note="法术打恶魔干扰者 → 酒馆全体 +1/+2 this game；邪能野猪人每 3 张法术吞一个酒馆随从"))

# C. rank6「Demon Boost Shop」：干扰者 + 鬼影幻术师 + 巴琳达 + 野猪人
_reg(CompSpec(
    "C", "Demon Boost Shop", "demon_boost_shop", "DEMON",
    core=("BG36_762", "BG36_731", "BG35_883", "BG28_633"),
    carrier=("BG28_633",), cast_on=("BG36_762",),
    type_min=4, trinkets=("BG36_MagicItem_831", "BG32_MagicItem_821",
                          "BG36_MagicItem_830"),
    curve=CURVE_FAST, tavern_buy=True,
    note="同 B 的酒馆 buff 引擎，用鬼影幻术师（Methodical Madness）补法术密度"))

# D. rank13「Elemental Azerite」：活化艾泽里特（酒馆元素 +4/+3 this game）+ 地卜师 + 巴琳达
_reg(CompSpec(
    "D", "Elemental Azerite", "elemental_azerite", "ELEMENTAL",
    core=("BG28_707", "BG35_881", "BG35_883", "BG_LOE_077"),
    carrier=("BG28_707",), cast_on=("BG28_707",),
    type_min=4, trinkets=("BG30_MagicItem_431", "BG35_MagicItem_861",
                          "BG35_MagicItem_862"),
    curve=CURVE_MID, tavern_buy=True,
    note="每张酒馆法术给酒馆元素 +4/+3 this game；被养肥的元素买进来就是载体身材"))

# E. rank25「Mech Glambot」：炫彩机器人（法术打机械 → 磁力 4/4）+ 巴琳达 + 多面无人机
_reg(CompSpec(
    "E", "Mech Glambot", "mech_glambot", "MECHANICAL",
    core=("BG36_853", "BG35_883", "BG26_152", "BG26_ICC_901"),
    carrier=("BG36_853",), cast_on=("BG36_853",),
    type_min=3, trinkets=("BG30_MagicItem_942", "BG35_MagicItem_741",
                          "BG32_MagicItem_808t"),
    curve=CURVE_MID,
    note="所有法术打同一个机械 → 炫彩机器人每次磁力 4/4 卫星，全部叠在载体上"))

# F. rank10「Dragon Spell Power」：符文奥术师 + 赤红守备巨龙 + 执念诗心龙
_reg(CompSpec(
    "F", "Dragon Spell Power", "dragon_spell_power", "DRAGON",
    core=("BG36_245", "BG36_241", "BG29_813", "BG_LOE_077"),
    carrier=("BG36_241",), cast_on=("BG36_241",),
    type_min=2, trinkets=("BG30_MagicItem_995", "BG30_MagicItem_902",
                          "BG30_MagicItem_433"),
    curve=CURVE_MID,
    note="法强养大赤红守备巨龙；龙系身材靠执念诗心龙在战斗里留存"))

# V2 F 龙链：塔蕾 + 诗人 + 奥术师 + 融合怪；保留旧版 F 不变。
_reg(CompSpec(
    "f_dragon", "F Dragon Chain V2", "f_dragon", "DRAGON",
    core=("BG21_015", "BG29_813", "BG36_245", "BG36_640"),
    carrier=("BG21_015",), cast_on=("BG21_015",), type_min=2,
    trinkets=("BG32_MagicItem_417", "BG32_MagicItem_364", "BG30_MagicItem_995"),
    curve=(2, 2, 3, 4, 4, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6),
    enabler=("BG29_813", "BG36_245", "BG36_640"),
    filler=("BG24_500", "BG34_631", "BG29_814"),
    note="V2：核心优先塔蕾/诗人/奥术师/融合怪；法术优先打塔蕾，t8 未见核心退通用"))

_reg(CompSpec(
    "G", "Beast Beetle", "beast_beetle", "BEAST",
    core=("BG36_209", "BG31_809", "BG36_204", "BG26_802"),
    carrier=("BG36_209",), cast_on=("BG36_209",),
    type_min=3, trinkets=("BG32_MagicItem_860t", "BG30_MagicItem_540",
                          "BGDUO_MagicItem_003"),
    curve=CURVE_MID,
    note="甲虫身材 this game + 香蕉猛猿翻倍；招募期只能买齐组件"))

# H. rank11「Murloc End Of Turn」：小瞎眼 + 布莱恩 + 达卡莱 + 魔鳍真菌学家
_reg(CompSpec(
    "H", "Murloc End Of Turn", "murloc_end_of_turn", "MURLOC",
    core=("BG22_403", "BG_LOE_077", "BG26_ICC_901", "BG33_891"),
    carrier=("BG22_403",), cast_on=("BG22_403",),
    type_min=2, trinkets=("BG32_MagicItem_925", "BG32_MagicItem_892",
                          "BG36_MagicItem_850"),
    curve=CURVE_MID,
    note="回合结束触发相邻战吼（小瞎眼）+ 布莱恩翻倍 + 达卡莱再翻倍"))

# I. rank8「Mech APM」：自动起床号 + 火花破坏机 + 经济
_reg(CompSpec(
    "I", "Mech APM", "mech_apm", "MECHANICAL",
    core=("BG36_367", "BG36_851", "BG_LOE_077"),
    carrier=("BG36_367",), cast_on=("BG36_367",),
    type_min=2, trinkets=("BG30_MagicItem_942", "BG35_MagicItem_741",
                          "BG36_MagicItem_810"),
    curve=CURVE_MID,
    note="每买 3 张牌磁力一个 Volumizer 到载体（APM 引擎，招募期可全自动）"))

# J. rank15「Mech Volumizer」：机智的机器人 + 多面辅助无人机 + 达卡莱
_reg(CompSpec(
    "J", "Mech Volumizer", "mech_volumizer", "MECHANICAL",
    core=("BG36_366", "BG26_152", "BG26_ICC_901"),
    carrier=("BG36_366",), cast_on=("BG36_366",),
    type_min=2, trinkets=("BG30_MagicItem_942", "BG30_MagicItem_435",
                          "BG35_MagicItem_741"),
    curve=CURVE_MID,
    note="回合结束磁力 Volumizer 到载体；多面无人机按磁力层数给全队 +4/+5，达卡莱翻倍"))

# K. rank21「Beast Leviathan」：深潜巨兽 + 下水道老鼠头目 + 香蕉猛猿
_reg(CompSpec(
    "K", "Beast Leviathan", "beast_leviathan", "BEAST",
    core=("BG35_602", "BG35_604", "BG26_802", "BG36_204"),
    carrier=("BG35_602",), cast_on=("BG35_602",),
    type_min=3, trinkets=("BG32_MagicItem_860t", "BG36_MagicItem_450",
                          "BG30_MagicItem_435"),
    curve=CURVE_MID,
    note="召唤野兽 → 深潜巨兽永久 +3 攻；老鼠头目+猛猿在战斗里放大"))

# L. rank26「Quilboar Gem Spam」：热气球测绘员 + 地卜大师鲁古格 + 棘刺挖掘工 + 巴琳达
_reg(CompSpec(
    "L", "Quilboar Gem Spam", "quilboar_gem_spam", "QUILBOAR",
    core=("BG30_121", "BG28_583", "BG36_331", "BG35_883"),
    carrier=("BG28_583",), cast_on=("BG28_583",),
    type_min=3, trinkets=("BG30_MagicItem_442", "BG32_MagicItem_808t",
                          "BG30_MagicItem_943"),
    curve=CURVE_MID,
    note="鲜血宝石当法术刷：测绘员让宝石多打一次，鲁古格把宝石溅到别的随从"))

# M. rank7「Murloc Handbuff」：暮光猎潮者 + 布莱恩 + 合唱鱼人 + 好斗的斥候
_reg(CompSpec(
    "M", "Murloc Handbuff", "murloc_handbuff", "MURLOC",
    core=("BG36_703", "BG_LOE_077", "BG26_354", "BG32_330"),
    carrier=("BG36_703",), cast_on=("BG36_703",),
    type_min=3, trinkets=("BG30_MagicItem_914", "BG30_MagicItem_710",
                          "BGDUO_MagicItem_003"),
    curve=CURVE_MID,
    note="法术打暮光猎潮者 → 手牌最左 +8/+8；合唱鱼人在开战时吃掉手牌身材"))

# N. rank22「Undead Eternal Knight」：永恒骑士 + 永恒召唤者（无限复生）
_reg(CompSpec(
    "N", "Undead Eternal Knight", "undead_eternal_knight", "UNDEAD",
    core=("BG25_009", "BG25_008", "BG36_848", "BG25_354"),
    carrier=("BG25_008",), cast_on=("BG25_008",),
    type_min=2, trinkets=("BG30_MagicItem_301", "BGDUO_MagicItem_003",
                          "BG30_MagicItem_435"),
    curve=CURVE_MID,
    note="永恒召唤者亡语召唤永恒骑士，骑士按本局死亡数成长（招募期只能攒组件）"))

#: 不可实现（理由写进 docs/COMP_SCRIPTS.md §5）
UNIMPLEMENTABLE: Dict[str, str] = {
    "murloc_scam": "Sewer Escapee/Bile Spitter 全靠 Activate + 战斗进击，招募期无法结算",
    "aberration_discard": "需要弃牌链（Mysterious K'Thir 弃 Sludge Corrosion）+ Deity 目标",
    "undead_apm": "bounty 只在战斗中生成，招募期无 bounty 密度",
    "undead_butcher": "Butchering 是战斗内亡语链（Snazzy Phantom 右端亡灵）",
    "dragon_shield": "圣盾重置链（Nadina/Hopebringer）在战斗内结算",
    "aberration_deathrattle": "Faceless Converter 亡语给 Deity，成长全在战斗",
    "pirate_discover": "Hooktusk 收益来自 Discover 循环，脚本拿不到稳定 Discover 密度",
    "demon_self_damage": "Ashen Corruptor/Soul Rewinder 需要英雄掉血触发器，招募期无掉血",
    "elemental_tempest": "Unbound Tempest 靠 Brann 反复战吼，需要元素生成链 + 战斗结算",
    "beast_lobster": "Tasty Lobster 亡语 + Deathstrider 左端亡语链，招募期不可测",
    "quilboar_choose_one": "Turbo Hogrider 需要抉择牌循环，脚本无法稳定刷抉择",
    "pirate_bounty": "Selfish Bounty 战斗内结算",
    "dragon_kalecgos": "Kalecgos 战吼循环收益在战吼密度，无战斗无法测",
}


# ── 通用工具 ───────────────────────────────────────────────────────────────
def price_of(it: dict) -> int:
    for k in ("price", "cost"):
        v = it.get(k)
        if isinstance(v, int) and v >= 0:
            return v
    return 3


def strength_of(m: dict) -> int:
    return int(m.get("atk") or 0) + int(m.get("hp") or 0)


def races_of(m: dict) -> List[str]:
    return [str(r) for r in (m.get("races") or [])]


def is_minion(it: dict) -> bool:
    return str(it.get("type") or "minion") == "minion"


# ── 策略 ───────────────────────────────────────────────────────────────────
class CompPolicy:
    """核心卡 + 载体的显式优先级脚本；``act(view, mask)`` 只返回 mask 内动作。"""

    def __init__(self, spec: Optional[CompSpec], *, auto: bool = False, seed: int = 0,
                 max_refresh: int = 4, exit_turn: int = 10):
        self.spec0 = spec
        self.spec = spec
        self.auto = bool(auto)
        self.max_refresh = int(max_refresh)
        self.exit_turn = int(exit_turn)
        self.rng = np.random.default_rng(int(seed))
        self.turn = -1
        self.refreshes = 0
        self.actions = 0
        self.replaced = 0
        self.illegal = 0
        self.exited = False
        self.casts_target = 0
        self.casts_on_aim = 0
        self.casts_on_carrier = 0
        self.spells = 0
        self.core_seen: Dict[str, int] = {}
        self.carrier_turn = -1
        self.snaps: List[dict] = []
        self.trinket_ids: List[str] = []

    # -- 规格集合 -----------------------------------------------------------
    @property
    def core_ids(self) -> set:
        return expand(self.spec.core) if self.spec else set()

    @property
    def carrier_ids(self) -> set:
        return expand(self.spec.carrier) if self.spec else set()

    @property
    def aim_ids(self) -> set:
        return expand(self.spec.aim) if self.spec else set()

    # -- 入口 ---------------------------------------------------------------
    def observe(self, v: dict, mask: np.ndarray) -> None:
        """每次决策前调用：记录回合快照 + 重置每回合计数器（纯脚本与混合模式共用）。"""
        v["_mask"] = mask
        t = int(v.get("turn") or 0)
        if t != self.turn:
            self.turn = t
            self.refreshes = 0
            self.actions = 0
            self.replaced = 0
            self._snapshot(v)

        if self.spec0 is not None and self.spec0.key == "f_dragon":
            me = v.get("me") or {}
            for m in (me.get("hand") or []) + (me.get("board") or []):
                cid = str(m.get("id"))
                base = cid[:-2] if cid.endswith("_G") else cid
                if base in self.spec0.core:
                    self.core_seen.setdefault(base, t)
            if any(str(m.get("id")) in expand(self.spec0.carrier)
                   for m in (me.get("board") or [])) and self.carrier_turn < 0:
                self.carrier_turn = t

    def act(self, v: dict, mask: np.ndarray) -> int:
        self.observe(v, mask)
        me = v.get("me") or {}
        if me.get("pending"):
            return self._safe(self._pending(v, me, me["pending"]), mask)
        if v.get("phase") != "recruit" or me.get("ended_turn"):
            return self._safe(A_END, mask)
        self.actions += 1
        if self.actions > 240:
            return self._safe(A_END, mask)
        if self.auto:
            self._auto_pick(me)
        return self._safe(self._recruit(v, me, mask), mask)

    def _safe(self, a: int, mask: np.ndarray) -> int:
        if 0 <= int(a) < 245 and bool(mask[int(a)]):
            return int(a)
        self.illegal += 1
        if bool(mask[A_END]):
            return A_END
        nz = np.flatnonzero(mask)
        return int(nz[0]) if nz.size else A_END

    # -- auto：进入 / 退出 --------------------------------------------------
    def _auto_pick(self, me: dict) -> None:
        if self.spec is not None and not self.exited:
            return
        t = int(self.turn)
        board_ids = {str(m.get("id")) for m in (me.get("board") or [])}
        hand_ids = {str(m.get("id")) for m in (me.get("hand") or [])}
        shop_ids = {str(m.get("id")) for m in (me.get("shop") or [])}
        tier = int(me.get("tier") or 1)
        best, best_key = None, None
        for sp in COMPS.values():
            if sp.key == "f_dragon":
                continue
            core = expand(sp.core)
            n_own = len(core & (board_ids | hand_ids))
            n_shop = len(core & shop_ids)
            need_tier = max((tier_of(c) for c in sp.core), default=6)
            if n_own == 0 and n_shop == 0:
                continue
            # 分数 = 已有核心数（3）+ 商店核心（1.2）+ tier 够得着（1）；t 越大越保守
            score = 3.0 * n_own + 1.2 * n_shop + (1.0 if tier >= need_tier - 1 else 0.0)
            score -= 0.15 * max(0, t - 6)
            if score <= 0:
                continue
            key = (score, n_own, -t)
            if best_key is None or key > best_key:
                best, best_key = sp, key
        if best is not None and best_key[0] > 0:
            self.spec = best
            return
        if t >= self.exit_turn and not self._core_owned(me):
            self.exited = True
            self.spec = None

    def _core_owned(self, me: dict) -> bool:
        if self.spec is None:
            return False
        ids = {str(m.get("id")) for m in (me.get("board") or [])}
        ids |= {str(m.get("id")) for m in (me.get("hand") or [])}
        return bool(self.core_ids & ids)

    def _f_core_count(self, me: dict) -> int:
        """F V2 已拥有的不同核心数（手牌或棋盘，金色按普通牌归一）。"""
        if self.spec is None or self.spec.key != "f_dragon":
            return 0
        ids = {str(m.get("id")) for m in (me.get("board") or []) + (me.get("hand") or [])}
        base = {x[:-2] if x.endswith("_G") else x for x in ids}
        return len({x for x in self.spec.core if x in base})

    def _f_can_roll(self, me: dict) -> bool:
        """F V2 只在已有核心、血量安全且升本后仍留三金时找伴生。"""
        if self.spec is None or self.spec.key != "f_dragon":
            return True
        hp = int(me.get("health") or 0)
        if hp <= 20:
            return False
        up = int(me.get("upgrade_price") or 99)
        gold = int(me.get("gold") or 0)
        return self._f_core_count(me) >= 1 and gold >= up + 3

    # -- 回合快照 -----------------------------------------------------------
    def _snapshot(self, v: dict) -> None:
        me = v.get("me") or {}
        board = me.get("board") or []
        t = int(v.get("turn") or 0)
        types = set()
        for m in board:
            types |= set(races_of(m))
        car = [m for m in board if str(m.get("id")) in self.carrier_ids]
        core = [m for m in board if str(m.get("id")) in self.core_ids]
        for c in core:
            cid = str(c.get("id"))
            self.core_seen.setdefault(cid[:-2] if cid.endswith("_G") else cid, t)
        if car and self.carrier_turn < 0:
            self.carrier_turn = t
        self.snaps.append({
            "turn": t, "strength": sum(strength_of(m) for m in board),
            "tier": int(me.get("tier") or 0), "board": len(board),
            "types": len(types), "carrier": sum(strength_of(m) for m in car),
            "carrier_n": len(car), "gold": int(me.get("gold") or 0),
            "core_n": len(core), "health": int(me.get("health") or 0),
        })

    # -- 强制选择 -----------------------------------------------------------
    def _pending(self, v: dict, me: dict, pend: Any) -> int:
        mask = v["_mask"]
        legal = [i for i in range(N_CHOICE) if bool(mask[A_CHOOSE + i])]
        if not legal:
            return A_CHOOSE
        p = pend[0] if isinstance(pend, list) and pend else pend
        if not isinstance(p, dict):
            return A_CHOOSE + legal[0]
        kind = str(p.get("kind"))
        opts = p.get("options") or p.get("targets") or []
        board = me.get("board") or []

        if kind in ("target", "targets"):
            aim = [m for m in board if str(m.get("id")) in self.aim_ids]
            car = [m for m in board if str(m.get("id")) in self.carrier_ids]
            aim_e = {int(x.get("eid") or -1) for x in aim}
            self.casts_target += 1
            for i in legal:
                if i < len(opts) and int(opts[i]) in aim_e:
                    self.casts_on_aim += 1
                    if int(opts[i]) in {int(x.get("eid") or -1) for x in car}:
                        self.casts_on_carrier += 1
                    return A_CHOOSE + i
            if board:                     # 无载体/放大器：打在最大身材上
                best = max(board, key=strength_of)
                for i in legal:
                    if i < len(opts) and int(opts[i]) == int(best.get("eid") or -1):
                        return A_CHOOSE + i
            return A_CHOOSE + legal[0]

        if kind == "hero":
            best = None
            for i in legal:
                if i >= len(opts) or not isinstance(opts[i], dict):
                    continue
                hp = opts[i].get("hero_power") or {}
                txt = str(hp.get("text") or "").lower()
                sc = (3.0 if "+" in txt else 0.0) - 0.1 * float(hp.get("cost") or 0)
                sc += 0.01 * float(opts[i].get("armor") or 0)
                if best is None or sc > best[0]:
                    best = (sc, i)
            return A_CHOOSE + (best[1] if best else legal[0])

        if kind == "trinket":
            gold = int(me.get("gold") or 0)
            want = expand(self.spec.trinkets) if self.spec else set()
            best = None
            for i in legal:
                if i >= len(opts) or not isinstance(opts[i], dict):
                    continue
                o = opts[i]
                cid = str(o.get("id") or "")
                cost = int(o.get("cost") or 0)
                sc = 100.0 if cid in want else 0.0
                txt = str(o.get("text") or "").lower()
                if self.spec0 is not None and self.spec0.key == "f_dragon":
                    chain = self._f_core_count(me) > 0 or gold >= 6
                    growth = any(w in txt for w in ("dragon", "spell", "combat", "adjacent"))
                    survival = any(w in txt for w in ("health", "shield", "armor", "damage"))
                    if self.turn >= 6 or chain:
                        sc += 150.0 if cid in want else 40.0 if growth else 0.0
                    elif survival:
                        sc += 200.0
                if "spell" in txt or "tavern" in txt:
                    sc += 8.0
                if "gold" in txt or "buy" in txt or "refresh" in txt:
                    sc += 6.0
                if "blood gem" in txt:
                    sc += 4.0
                if "magnetiz" in txt:
                    sc += 4.0
                sc -= 0.5 * max(0, cost - gold)
                if best is None or sc > best[0]:
                    best = (sc, i)
            if best is not None and isinstance(opts[best[1]], dict):
                self.trinket_ids.append(str(opts[best[1]].get("id") or ""))
            return A_CHOOSE + (best[1] if best else legal[0])

        # discover / choose_one / 其它
        core, car = self.core_ids, self.carrier_ids
        board_races = set()
        for m in board:
            board_races |= set(races_of(m))
        best = None
        for i in legal:
            if i >= len(opts) or not isinstance(opts[i], dict):
                continue
            o = opts[i]
            cid = str(o.get("id") or "")
            sc = float(strength_of(o)) if is_minion(o) else 0.0
            if cid in core:
                sc += 300.0
            elif cid in car:
                sc += 120.0
            elif is_minion(o) and set(races_of(o)) and not (set(races_of(o)) & board_races):
                sc += 25.0
            if best is None or sc > best[0]:
                best = (sc, i)
        return A_CHOOSE + (best[1] if best else legal[0])

    # -- 混合模式：只接管「阵容相关」的动作，其余交给引擎 bot ------------------
    def comp_action(self, v: dict, mask: np.ndarray) -> Optional[int]:
        """返回阵容相关动作；``None`` = 交给引擎 bot（经济/升本/站位由 bot 兜底）。

        触发规则（与纯脚本同源）：
        ① 商店有核心 → 买；② 核心齐 → 所有法术只打载体；③ 优先买未拥有的类型；
        ④ 满场卖无 buff 价值的随从（由 bot 的卖牌逻辑兜底，脚本不抢）。
        """
        me = v.get("me") or {}
        if me.get("pending"):
            return self._pending(v, me, me["pending"])
        if v.get("phase") != "recruit":
            return None
        spec = self.spec
        if spec is None:
            return None
        gold = int(me.get("gold") or 0)
        board = me.get("board") or []
        hand = me.get("hand") or []
        shop = me.get("shop") or []
        hand_ids = {str(it.get("id")) for it in hand}
        hand_minions = [it for it in hand if is_minion(it)]
        hand_spells = [h for h, it in enumerate(hand[:N_HAND]) if not is_minion(it)]
        room = N_BOARD - len(board)
        aim_on_board = any(str(m.get("id")) in self.aim_ids for m in board)

        # ① 法术只打载体/放大器（无落点就先不打）
        if hand_spells and aim_on_board:
            for h in hand_spells:
                a = A_PLAY + h * N_POS
                if 0 <= a < 245 and bool(mask[a]):
                    self.spells += 1
                    return a

        buys = [(i, shop[i]) for i in range(N_SHOP)
                if i < len(shop) and bool(mask[A_BUY + i])]
        core, car = self.core_ids, self.carrier_ids

        # ② 商店有核心 → 买（同名去重；手牌有空位）
        if len(hand) < N_HAND:
            cores = [(i, it) for i, it in buys
                     if str(it.get("id")) in core and str(it.get("id")) not in hand_ids]
            if cores:
                i, it = min(cores, key=lambda kv: price_of(kv[1]))
                if gold >= price_of(it):
                    return A_BUY + i

        # ③ 买载体
        if len(hand) < N_HAND:
            cars = [(i, it) for i, it in buys
                    if str(it.get("id")) in car and str(it.get("id")) not in hand_ids]
            if cars:
                i, it = min(cars, key=lambda kv: price_of(kv[1]))
                if gold >= price_of(it):
                    return A_BUY + i

        # ④ 优先买「未拥有的种族类型」（有空位时才占用金币）
        board_races = set()
        for m in board:
            board_races |= set(races_of(m))
        if room > 0 and len(hand_minions) == 0 and len(board_races) < spec.type_min:
            fills = [(i, it) for i, it in buys
                     if is_minion(it) and set(races_of(it))
                     and not (set(races_of(it)) & board_races)
                     and str(it.get("id")) not in core]
            if fills:
                i, it = max(fills, key=lambda kv: strength_of(kv[1]))
                if gold >= price_of(it):
                    return A_BUY + i
        return None

    def _recruit_f(self, v: dict, me: dict, mask) -> int:
        """F V2 分阶段经济：核心/伴生链优先，刷新与转本均有硬门槛。"""
        legal = lambda a: 0 <= a < 245 and bool(mask[a])
        board, hand, shop = (me.get(k) or [] for k in ("board", "hand", "shop"))
        turn, gold = self.turn, int(me.get("gold") or 0)
        tier, hp = int(me.get("tier") or 1), int(me.get("health") or 0)
        up = int(me.get("upgrade_price", 99))
        spec = self.spec
        if turn >= 8 and not self._f_core_count(me):
            self.exited, self.spec = True, None
            spec = None
        core = self.core_ids
        own = [str(x.get("id")) for x in board + hand]
        enabler = expand(spec.enabler) if spec else set()
        protected = core | enabler
        buys = [(i, x) for i, x in enumerate(shop[:N_SHOP])
                if legal(A_BUY + i) and gold >= price_of(x)]
        # t2 升本；t3–7 常规曲线；t8+ 转本须核心在手、血量安全且剩三金。
        due = tier < (self._curve_tier(turn) if spec else 6)
        can_upgrade = (turn == 2 or (turn >= 3 and due and len(board) >= 4))
        if turn >= 8:
            can_upgrade = can_upgrade and bool(core & set(own)) and hp > 20 and gold >= up + 3
        if legal(A_UPGRADE) and gold >= up and can_upgrade:
            self.upgraded_turn = turn
            return A_UPGRADE
        # 升本回合不追重复牌/三连；优先铺手牌，避免刷新前空场。
        for h, it in sorted(enumerate(hand[:N_HAND]),
                            key=lambda kv: (str(kv[1].get("id")) not in core,
                                            -strength_of(kv[1]))):
            if is_minion(it) and len(board) < N_BOARD:
                a = A_PLAY + h * N_POS + len(board)
                if legal(a):
                    return a
            elif not is_minion(it) and any(str(m.get("id")) in self.aim_ids for m in board):
                a = A_PLAY + h * N_POS
                if legal(a):
                    self.spells += 1
                    return a
        def score(it):
            cid = str(it.get("id"))
            if turn <= 2:
                return strength_of(it)
            order = spec.core.index(cid) if spec and cid in spec.core else 9
            return (1000 - order * 20 if cid in core else
                    700 if cid in enabler else
                    100 if spec and cid in expand(spec.filler) else 0) + strength_of(it)
        candidates = [(i, it) for i, it in buys if is_minion(it)
                      and not (getattr(self, "upgraded_turn", -1) == turn
                               and str(it.get("id")) in own)]
        candidates.sort(key=lambda kv: score(kv[1]), reverse=True)
        # t13+ 撤掉无成长价值的经济位，金币留给刷新/核心三连。
        if turn >= 13 and spec:
            econ = [(strength_of(m), j) for j, m in enumerate(board)
                    if str(m.get("id")) not in protected
                    and any(w in str((CATALOG.get(str(m.get("id"))) or {}).get("text", "")).lower()
                            for w in ("gold", "coin")) and legal(A_SELL + j)]
            if econ and candidates:
                return A_SELL + min(econ)[1]
        if candidates and len(hand) < N_HAND:
            i, it = candidates[0]
            cid = str(it.get("id"))
            if len(board) < N_BOARD:
                return A_BUY + i
            sell = [(strength_of(m), j) for j, m in enumerate(board)
                    if str(m.get("id")) not in protected and legal(A_SELL + j)]
            if sell and self.replaced < 2 and (cid in core or strength_of(it) > min(sell)[0] + 5):
                self.replaced += 1
                return A_SELL + min(sell)[1]
        if spec and any(str(m.get("id")) in self.aim_ids for m in board):
            spells = [(i, x) for i, x in buys if not is_minion(x)]
            if spells and len(hand) < N_HAND - 1:
                return A_BUY + min(spells, key=lambda kv: price_of(kv[1]))[0]
        # 转通用后仍执行安全刷新门槛；不让退出状态绕过生命/经济约束。
        can_roll = self._f_can_roll(me) if spec else (hp > 20 and gold >= up + 3)
        if legal(A_REFRESH) and can_roll and self.refreshes < self.max_refresh:
            self.refreshes += 1
            return A_REFRESH
        return A_END

    # -- 招募 ---------------------------------------------------------------
    def _recruit(self, v: dict, me: dict, mask) -> int:
        if self.spec0 is not None and self.spec0.key == "f_dragon":
            return self._recruit_f(v, me, mask)
        def legal(a: int) -> bool:
            return 0 <= a < 245 and bool(mask[a])

        gold = int(me.get("gold") or 0)
        tier = int(me.get("tier") or 1)
        turn = int(self.turn)
        board = me.get("board") or []
        hand = me.get("hand") or []
        shop = me.get("shop") or []
        spec = self.spec
        core, car = self.core_ids, self.carrier_ids
        board_races = set()
        for m in board:
            board_races |= set(races_of(m))
        hand_minions = [(i, it) for i, it in enumerate(hand[:N_HAND]) if is_minion(it)]
        hand_spells = [(i, it) for i, it in enumerate(hand[:N_HAND]) if not is_minion(it)]
        buys = [(i, shop[i]) for i in range(N_SHOP) if i < len(shop) and legal(A_BUY + i)]
        aim_on_board = [m for m in board if str(m.get("id")) in self.aim_ids]
        carrier_on_board = [m for m in board if str(m.get("id")) in car]
        hand_ids = {str(it.get("id")) for it in hand}
        board_ids = [str(m.get("id")) for m in board]
        hand_free = len(hand) < N_HAND
        type_need = (max(0, spec.type_min - len(board_races)) if spec else 0)

        def want_core(it): return str(it.get("id")) in core
        def want_carrier(it): return str(it.get("id")) in car
        def new_type(it):
            rs = set(races_of(it))
            return bool(rs) and not (rs & board_races)

        slots = N_BOARD - len(board) - len(hand_minions)   # 还能再上场几张
        room = N_BOARD - len(board)                        # 棋盘空位
        missing_core = bool(spec) and not (self.core_ids & (set(board_ids) | hand_ids))

        def better(a: dict, b: dict) -> bool:
            """a 是否明显强于 b：高一级 tier，或身材多 15 以上。"""
            ta, tb = tier_of(str(a.get("id"))), tier_of(str(b.get("id")))
            return ta > tb or strength_of(a) > strength_of(b) + 15

        worst = self._sellable(board) if len(board) >= N_BOARD else None

        def shop_key(it: dict) -> float:
            """酒馆买牌打分：tavern_buy 阵容看身材（已被 this-game 酒馆 buff 养肥），
            其余阵容看 tier 优先、身材次之。"""
            if spec is not None and spec.tavern_buy:
                return float(strength_of(it))
            return 10.0 * tier_of(str(it.get("id"))) + strength_of(it)

        best_shop = max(((i, it) for i, it in buys if is_minion(it)),
                        key=lambda kv: shop_key(kv[1]), default=None)

        def better(a: dict, b: dict) -> bool:
            """a 是否明显强于 b：高一级 tier，或身材多 15 以上。"""
            if spec is not None and spec.tavern_buy:
                return strength_of(a) > strength_of(b) + 5
            ta, tb = tier_of(str(a.get("id"))), tier_of(str(b.get("id")))
            return ta > tb or strength_of(a) > strength_of(b) + 15

        def buyable(it: dict) -> bool:
            """值得买：空位多（铺场）或明显强于最弱可卖位（置换）。"""
            if len(board) < 4:
                return True
            if worst is not None:
                return better(it, board[worst])
            return len(board) < N_BOARD

        # ── ① 满场置换：只卖「无类型 / 无 buff 价值」的最弱随从（核心/载体永不卖）──
        #    必须有明确的接替者（商店核心/载体或明显更强的牌），且每回合最多换 2 张，
        #    否则会把金币全烧在「卖了又买」的横向上，永远升不到 5/6 本。
        up = int(me.get("upgrade_price") or 99)
        want_tier = self._curve_tier(turn)
        on_schedule = turn >= EARLIEST_TIER.get(min(tier + 1, 6), 99)
        # 升本优先于横向置换：4→5 要 8 金、5→6 要 10 金，漏掉这个回合就再也升不上去。
        if (legal(A_UPGRADE) and tier < want_tier and on_schedule
                and gold >= up and len(board) >= 4):
            return A_UPGRADE

        if worst is not None and self.replaced < 2:
            want_shop = [(i, it) for i, it in buys
                         if (want_core(it) or want_carrier(it)) and gold >= price_of(it)]
            if want_shop:
                self.replaced += 1
                return A_SELL + worst
            if (best_shop is not None and gold >= price_of(best_shop[1])
                    and better(best_shop[1], board[worst])):
                self.replaced += 1
                return A_SELL + worst

        # ── ② 手牌法术 → 只打载体/放大器（核心不接 buff）───────────────────
        if hand_spells:
            cast_now = bool(aim_on_board)
            if not cast_now and len(hand) >= 8:
                cast_now = bool(board)          # 手牌堵死：先清法术，别卡死
            if cast_now:
                for h, _it in hand_spells:
                    a = A_PLAY + h * N_POS
                    if legal(a):
                        self.spells += 1
                        return a

        # ── ③ 手牌随从：核心 → 载体 → 新类型 → 大身材（有空位才上）─────────
        if hand_minions and room > 0:
            def rank(kv):
                _h, it = kv
                if want_core(it):
                    r = 0
                elif want_carrier(it):
                    r = 1
                elif type_need > 0 and new_type(it):
                    r = 2
                else:
                    r = 3
                return (r, -strength_of(it))
            h, it = sorted(hand_minions, key=rank)[0]
            a = A_PLAY + h * N_POS + len(board)
            if legal(a):
                return a

        # ── ④ 商店有核心 → 买（刷新 ≤4 次/回合）───────────────────────────
        cores = [(i, it) for i, it in buys
                 if want_core(it) and str(it.get("id")) not in hand_ids]
        if cores and hand_free:
            i, it = min(cores, key=lambda kv: price_of(kv[1]))
            if gold >= price_of(it):
                return A_BUY + i

        # ── ⑤ 买载体（没有载体，法术无处落点）─────────────────────────────
        cars = [(i, it) for i, it in buys
                if want_carrier(it) and str(it.get("id")) not in hand_ids]
        if cars and hand_free:
            i, it = min(cars, key=lambda kv: price_of(kv[1]))
            if gold >= price_of(it):
                return A_BUY + i

        # ── ⑥ 优先买「未拥有的种族类型」───────────────────────────────────
        if type_need > 0 and hand_free and room > 0:
            fills = [(i, it) for i, it in buys
                     if is_minion(it) and new_type(it) and not want_core(it)]
            if fills:
                i, it = max(fills, key=lambda kv: (tier_of(str(kv[1].get("id"))),
                                                   strength_of(kv[1])))
                if gold >= price_of(it):
                    return A_BUY + i

        # ── ⑦ 曲线升本已提到 ① 之前（避免被横向置换吃掉这个回合）──────────

        # ── ⑧ 买法术：有放大器/载体在场才买（留 2 个手牌位给随从）─────────
        if len(hand) <= N_HAND - 2:
            spells = [(i, it) for i, it in buys if not is_minion(it)]
            if spells:
                i, it = min(spells, key=lambda kv: price_of(kv[1]))
                ok = bool(aim_on_board) or len(hand_spells) < 1 or gold >= 12
                if ok and gold >= price_of(it):
                    return A_BUY + i

        # ── ⑨ 买最大身材（通用铺场 / 填线 / 撑过中期）─────────────────────
        if hand_free and room > 0 and best_shop is not None and not hand_minions:
            i, it = best_shop
            if gold >= price_of(it) and buyable(it):
                return A_BUY + i

        # ── ⑩ 刷新：缺核心时更积极（核心在 t5/t6，刷不到就废）─────────────
        rp = int(me.get("refresh_price") or 1)
        if missing_core and turn >= 6:
            budget = self.max_refresh + 6
        else:
            budget = self.max_refresh
        if (self.refreshes < budget and legal(A_REFRESH) and gold >= rp + 2
                and self._f_can_roll(me)):
            self.refreshes += 1
            return A_REFRESH

        # ── ⑪ 英雄技能 / 结束 ────────────────────────────────────────────
        for slot in range(2):
            if legal(A_HERO_POWER + slot) and gold >= 1:
                return A_HERO_POWER + slot
        return A_END

    def _curve_tier(self, turn: int) -> int:
        curve = self.spec.curve if self.spec else CURVE_MID
        return int(curve[min(max(turn - 1, 0), len(curve) - 1)])

    def _sellable(self, board: Sequence[dict]) -> Optional[int]:
        """卖「无类型 / 无 buff 价值」的最弱一个：核心/载体永不卖。"""
        cands = []
        for i, m in enumerate(board):
            cid = str(m.get("id"))
            if cid in self.core_ids or cid in self.carrier_ids:
                continue
            cands.append((1 if races_of(m) else 0, strength_of(m), i))
        if not cands:
            return None
        return min(cands)[2]


# ── 一局驱动 ───────────────────────────────────────────────────────────────
_HUMAN_POOL: Any = None


def _config_json(spec: Optional[CompSpec], seed: int) -> Optional[str]:
    """每套阵容保底 lobby：5 种类型里至少含阵容主族 + 4 个随机族（其余引擎默认）。"""
    rng = random.Random(int(seed) * 7919 + 13)
    others = [t for t in TRIBES if spec is None or t != spec.tribe]
    rng.shuffle(others)
    types = others[:5] if spec is None else [spec.tribe] + others[:4]
    return json.dumps({"lobby_types": list(types)})


def play_one(seed: int, spec: Optional[CompSpec], *, auto: bool = False,
             human_pool: Any = None, human_seats: int = 0, human_p: float = 0.0,
             human_fidelity: str = "full", max_steps: int = 4000,
             bot_seat0: bool = False, hybrid: bool = True) -> Optional[dict]:
    game = E.Game(int(seed), _config_json(spec, seed))
    EA.finish_hero_select(game)
    pol = CompPolicy(spec, auto=auto, seed=int(seed) % 100000)
    rng = random.Random(int(seed) * 1000003 + 17)
    stats = None
    if human_pool is not None and human_p > 0 and human_seats > 0:
        from hsbg.az.train.human_board_pool import HumanBoardStats, inject_turn
        stats = HumanBoardStats(fidelity=human_fidelity)
    last_turn = -1
    steps = 0
    illegal = 0
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            if stats is not None and t >= 1:
                try:
                    inject_turn(game, human_pool, t, seats_count=human_seats, p=human_p,
                                rng=rng, learner_seat=0, stats=stats, set_tier=True,
                                fidelity=human_fidelity, fast_inject=False)
                except BaseException:  # noqa: BLE001
                    pass
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p != 0:
                game.bot_play(p)
                continue
            if bot_seat0:
                a = int(game.bot_action(0))
            else:
                mask = mask_from_bytes(game.legal_mask(0))
                v = json.loads(game.view(0))
                if hybrid and not (pol.spec0 and pol.spec0.key == "f_dragon"):
                    # 混合：阵容动作优先，其余交给引擎 bot（经济/升本/站位兜底）
                    pol.observe(v, mask)
                    if pol.auto:
                        pol._auto_pick(v.get("me") or {})
                    ca = pol.comp_action(v, mask)
                    if ca is not None and 0 <= int(ca) < 245 and bool(mask[int(ca)]):
                        a = int(ca)
                    else:
                        a = int(game.bot_action(0))
                else:
                    a = int(pol.act(v, mask))
                if not (0 <= a < 245 and bool(mask[a])):
                    illegal += 1
                    nz = np.flatnonzero(mask)
                    a = int(nz[0]) if nz.size else A_END
            game.step(0, a)
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    place = list(game.placements())
    pj = json.loads(game.player_json(0))
    final = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                for m in (pj.get("board") or []))
    by_turn = {int(s["turn"]): s for s in pol.snaps}

    def at(t: int) -> dict:
        if t in by_turn:
            return by_turn[t]
        best: dict = {}
        for k in sorted(by_turn):
            if k <= t:
                best = by_turn[k]
        return best

    t15 = at(15)
    s15 = int(t15.get("strength") or final)
    s12 = int(at(12).get("strength") or 0)
    car15 = int(t15.get("carrier") or 0)
    st = pj.get("stats") or {}
    return {
        "seed": int(seed), "comp": (pol.spec.key if pol.spec else "generic"),
        "comp_name": (pol.spec.name if pol.spec else "generic"),
        "placement": int(place[0]) if place else 0,
        "sigma_t12": s12, "sigma_t15": s15, "final": final,
        "r12_15": (s15 / s12) if s12 > 0 else 0.0,
        "tier_t15": int(t15.get("tier") or 0),
        "types_t15": int(t15.get("types") or 0),
        "count_t15": int(t15.get("board") or 0),
        "carrier_stats": car15,
        "body_share": (car15 / s15) if s15 > 0 else 0.0,
        "casts_target": int(pol.casts_target),
        "casts_on_aim": int(pol.casts_on_aim),
        "casts_on_carrier": int(pol.casts_on_carrier),
        "cast_share": (pol.casts_on_aim / pol.casts_target) if pol.casts_target else 0.0,
        "spells": int(st.get("spells_cast") or 0),
        "tavern_spells": int(st.get("tavern_spells_cast") or 0),
        "core_turn": int(min(pol.core_seen.values()) if pol.core_seen else -1),
        "carrier_turn": int(pol.carrier_turn),
        "exited": bool(pol.exited),
        "trinkets": list(pol.trinket_ids),
        "illegal": int(illegal),
        "survival": len(pol.snaps),
        "turns": [{"t": s["turn"], "sigma": s["strength"], "tier": s["tier"],
                   "types": s["types"], "carrier": s["carrier"]} for s in pol.snaps],
    }


# ── 汇总 ───────────────────────────────────────────────────────────────────
def _pct(v: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(v, dtype=np.float64), q)) if len(v) else 0.0


def _mean(v: Sequence[float]) -> float:
    return float(np.mean(np.asarray(v, dtype=np.float64))) if len(v) else 0.0


def summarize(eps: Sequence[dict]) -> dict:
    s12 = [e["sigma_t12"] for e in eps]
    s15 = [e["sigma_t15"] for e in eps]
    ratios = [e["r12_15"] for e in eps]
    core_turns = [e["core_turn"] for e in eps if e["core_turn"] > 0]
    return {
        "games": len(eps),
        "sigma_t12_p50": _pct(s12, 50), "sigma_t12_p90": _pct(s12, 90),
        "sigma_t15_p50": _pct(s15, 50), "sigma_t15_p90": _pct(s15, 90),
        "sigma_t15_max": max(s15) if s15 else 0.0,
        "r12_15_p50": _pct(ratios, 50), "r12_15_p90": _pct(ratios, 90),
        "core_turn_p50": (_pct(core_turns, 50) if core_turns else -1.0),
        "core_rate": len(core_turns) / max(1, len(eps)),
        "carrier_rate": _mean([1.0 if e["carrier_turn"] > 0 else 0.0 for e in eps]),
        "cast_share": _mean([e["cast_share"] for e in eps]),
        "cast_share_ge50": _mean([1.0 if e["cast_share"] >= 0.5 else 0.0 for e in eps]),
        "body_share": _mean([e["body_share"] for e in eps]),
        "body_share_ge50": _mean([1.0 if e["body_share"] >= 0.5 else 0.0 for e in eps]),
        "spells_mean": _mean([e["spells"] for e in eps]),
        "tier_p50": _pct([e["tier_t15"] for e in eps], 50),
        "types_p50": _pct([e["types_t15"] for e in eps], 50),
        "placement_mean": _mean([e["placement"] for e in eps]),
        "top4_rate": _mean([1.0 if 0 < e["placement"] <= 4 else 0.0 for e in eps]),
        "illegal": int(sum(e["illegal"] for e in eps)),
        "exited_rate": _mean([1.0 if e["exited"] else 0.0 for e in eps]),
    }


# ── 多进程 ─────────────────────────────────────────────────────────────────
_G: Dict[str, Any] = {}


def _init_worker(payload: dict) -> None:
    _G.clear()
    _G.update(payload)
    global _HUMAN_POOL
    _HUMAN_POOL = None
    if payload.get("human_boards"):
        from hsbg.az.train.human_board_pool import load_pool
        _HUMAN_POOL = load_pool(str(payload["human_boards"]), sample="auto")


def _worker(job: dict) -> List[dict]:
    spec = COMPS.get(job["comp"]) if job["comp"] and job["comp"] != "BOT" else None
    out = []
    for k in range(int(job["games"])):
        r = play_one(int(job["seed0"]) + k, spec, auto=bool(job["auto"]),
                     human_pool=_HUMAN_POOL,
                     human_seats=int(_G.get("human_seats", 0)),
                     human_p=float(_G.get("human_p", 0.0)),
                     human_fidelity=str(_G.get("human_fidelity", "full")),
                     bot_seat0=(job["comp"] == "BOT"),
                     hybrid=bool(_G.get("hybrid", True)))
        if r is not None:
            out.append(r)
    return out


def run_comp(comp_key: Optional[str], games: int, workers: int, seed0: int,
             human_boards: str, human_seats: int, human_p: float,
             human_fidelity: str, auto: bool, hybrid: bool = True) -> List[dict]:
    import multiprocessing as mp
    n = max(1, min(int(workers), games))
    chunks = [(games + i) // n for i in range(n)]
    jobs = [{"comp": comp_key, "auto": auto, "games": c, "seed0": seed0 + 1000 * i}
            for i, c in enumerate(chunks) if c > 0]
    payload = {"human_boards": human_boards, "human_seats": human_seats,
               "human_p": human_p, "human_fidelity": human_fidelity,
               "hybrid": hybrid}
    with mp.get_context("fork").Pool(len(jobs), initializer=_init_worker,
                                     initargs=(payload,)) as pool:
        outs = pool.map(_worker, jobs)
    eps: List[dict] = []
    for o in outs:
        eps.extend(o)
    return eps


# ── CLI ────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="经典阵容脚本引擎（纯 CPU 全对局）")
    ap.add_argument("--comp", default="auto",
                    help="auto | all | BOT | 逗号分隔 key（A,B,L）")
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--configs", default="bot",
                    help="bot（8 席引擎 bot）| human（5 席 p0.9 人类战团）| bot,human")
    ap.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-seats", type=int, default=5)
    ap.add_argument("--human-p", type=float, default=0.9)
    ap.add_argument("--human-fidelity", default="full")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--pure", action="store_true",
                    help="纯手写经济脚本（不用引擎 bot 兜底；默认是混合模式）")
    ap.add_argument("--list", action="store_true")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        for k in sorted(COMPS):
            s = COMPS[k]
            print(f"{k:2s} {s.name:26s} tribe={s.tribe:12s} core={','.join(s.core)} "
                  f"carrier={','.join(s.carrier)} types={s.type_min}")
        return 0
    if args.comp == "all":
        keys: List[Optional[str]] = sorted(COMPS) + [None]
    elif args.comp == "auto":
        keys = [None]
    elif args.comp == "BOT":
        keys = ["BOT"]
    else:
        keys = [k.strip() for k in args.comp.split(",") if k.strip()]

    cfgs = [c.strip() for c in args.configs.split(",") if c.strip()]
    out: Dict[str, Any] = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "games": int(args.games), "configs": {}, "specs": {},
                           "unimplementable": UNIMPLEMENTABLE, "seconds": 0.0}
    for k in sorted(COMPS):
        s = COMPS[k]
        out["specs"][k] = {"name": s.name, "archetype": s.archetype, "tribe": s.tribe,
                           "core": list(s.core), "carrier": list(s.carrier),
                           "cast_on": list(s.cast_on), "type_min": s.type_min,
                           "trinkets": list(s.trinkets), "curve": list(s.curve),
                           "note": s.note}
    t0 = time.time()
    for cfg_name in cfgs:
        human = cfg_name == "human"
        out["configs"][cfg_name] = {}
        for key in keys:
            label = key or "auto"
            eps = run_comp(key, int(args.games), int(args.workers), int(args.seed0),
                           args.human_boards if human else "",
                           int(args.human_seats) if human else 0,
                           float(args.human_p) if human else 0.0,
                           str(args.human_fidelity), auto=(key is None),
                           hybrid=not bool(args.pure))
            rep = summarize(eps)
            rep["label"] = label
            out["configs"][cfg_name][label] = {
                "summary": rep, "episodes": [dict(e, turns=[]) for e in eps]}
            print(f"[{cfg_name}/{label:6s}] n={rep['games']:3d} "
                  f"t15Σ p50/p90={rep['sigma_t15_p50']:7.0f}/{rep['sigma_t15_p90']:8.0f} "
                  f"core_t={rep['core_turn_p50']:5.1f} cast={rep['cast_share']:.2f} "
                  f"body={rep['body_share']:.2f} spells={rep['spells_mean']:5.1f} "
                  f"r12_15={rep['r12_15_p50']:.2f} place={rep['placement_mean']:.2f} "
                  f"exc={rep['exited_rate']:.2f} ill={rep['illegal']}", flush=True)
    out["seconds"] = time.time() - t0
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, default=float)
        print(f"[comp_scripts] 写出 {args.json_out}")
    print(f"[comp_scripts] 总耗时 {out['seconds']:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
