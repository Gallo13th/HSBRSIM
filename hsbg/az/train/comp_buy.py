"""复利阵容的「条件式买卡规则」（B11）：什么时候必须买、什么时候恢复正常。

为什么需要条件：**无条件的买卡偏置会把策略变成"见卡就买"**——盘面已经成型时它会把
不该买的卡硬塞进来，反而毁掉强度。所以这里按 HSBG.md 的运营逻辑实现一个状态机：

    先判断启动条件（我们已经有什么），再决定是否限制购买；条件消失就恢复正常。

## 规则（v2，全部可用参数调节）

设 ``own = 我们场上 + 手牌的卡``，``cores(own)`` = own 里属于各复利阵容核心的数量。

1. **已承诺（sticky）**：若 own 里某阵容 C 有 ≥1 张非 MULT 核心
   ⇒ 进入 C 的"承诺模式"：
   - 商店出现 **C 的核心卡** 且该卡在 own 里 < ``max_copies``(默认 3) 张
   - 且 ``health > health_floor``(12) 且 ``turn <= late_turn``(17)
   ⇒ **必须买**（mask 只留这一张买入）——这就是"必须选"。
2. **开局（opening）**：own 里没有任何非 MULT 核心
   ⇒ 只对**乘算放大器**（布莱恩·铜须 / 达卡莱附魔师 / 提图斯·瑞文戴尔）和
   **早启动核心**（永恒骑士 t≤6、牺牲的愤怒卫士 t≤8、希望信使 t≤10）做**软偏置**
   （屏蔽其它购买，但允许刷新/升本/结束回合），且 ``health >= opening_health``(20)。
3. **恢复正常（release，完全不改写）** 的条件，任一成立即放行：
   a. ``health <= health_floor``：快死了，先保命要即时战力；
   b. ``turn > late_turn``：太晚，成长核心回不了本；
   c. 该卡在 own 里已达 ``max_copies``：再买是浪费；
   d. 商店里没有目标卡；
   e. own 里已有 ≥2 个不同阵容的核心（已经成型在别的线上）；
   f. 买不起（动作不合法，天然放行）。

## 与"禁卡"的区别

不动卡池、不改奖励；``comp_buy_bias=0`` 时逐位恒等。规则只影响**采集时的动作分布**，
所以学到的东西仍然来自真实对局回报（PPO 在改写后的策略上算 importance ratio）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Set, Tuple

import numpy as np

from hsbg.env.action_space_std import A_BUY, A_SELL, N_SHOP
from hsbg.env.obs_std import (
    GLOBAL_FIELD_INDEX, GLOBAL_FIELD_SCALE, N_BOARD, N_HAND,
    SLICE_CARD_BOARD, SLICE_CARD_HAND, SLICE_CARD_SHOP,
)

_DEFAULT_SPEC = "data/comp_cards.json"
_HEALTH = int(GLOBAL_FIELD_INDEX["health"])
_TURN = int(GLOBAL_FIELD_INDEX["turn"])

#: 开局窗口：这些核心卡攻略建议"最晚第 N 回合启动"，超过就没意义
EARLY_WINDOW = {"永恒骑士": 6, "牺牲的愤怒卫士": 8, "希望信使": 10, "德鲁斯特堕落屠夫": 8}


def _env_on() -> float:
    raw = (os.environ.get("HSBRSIM_COMP_BUY_BIAS", "") or "").strip()
    if raw in ("1", "true", "yes"):
        return 1.0
    try:
        return float(raw) if raw else 0.0
    except ValueError:
        return 0.0


def _env_spec() -> str:
    return (os.environ.get("HSBRSIM_COMP_CARDS", "") or "").strip() or _DEFAULT_SPEC


def _abs(p: str) -> str:
    if os.path.isabs(p):
        return p
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), p)


class CompSpec:
    """``data/comp_cards.json`` 的运行时视图（卡下标 → 阵容/类别）。"""

    def __init__(self, path: str = "", include: Tuple[str, ...] = ("MULT", "GROW")) -> None:
        spec = json.load(open(_abs(path or _env_spec()), encoding="utf-8"))
        self.include = tuple(str(x).upper() for x in include)
        self.card_comp: Dict[int, Set[str]] = {}
        self.card_name: Dict[int, str] = {}
        self.card_cat: Dict[int, str] = {}
        for comp in spec.get("comps") or []:
            cid = str(comp.get("id"))
            for nm, ids in zip(comp.get("core") or [], [None] * 10**6):
                pass
            # core 是名字列表，core_ids 是全量 id（顺序不一一对应）⇒ 用名字反查
            for nm in comp.get("core") or []:
                for cat, table in (spec.get("bias") or {}).items():
                    for i in table.get(nm) or []:
                        # cards 编码 = card_id + 1
                        self.card_comp.setdefault(int(i) + 1, set()).add(cid)
                        self.card_name.setdefault(int(i) + 1, nm)
                        self.card_cat.setdefault(int(i) + 1, cat)
        self.mult: Set[int] = {int(i) + 1 for i in (spec.get("mult_ids") or [])}
        self.grow: Set[int] = {int(i) + 1 for i in (spec.get("grow_ids") or [])}
        self.engine: Set[int] = {int(i) + 1 for i in (spec.get("engine_ids") or [])}
        self.mult_names = {self.card_name.get(i, "") for i in self.mult}
        for i in self.mult:
            self.card_cat[i] = "MULT"
        self._apply_include()

    def _apply_include(self) -> None:
        """按 ``include`` 裁剪目标：只保留指定类别（默认 MULT+GROW）。"""
        keep = {cid for cid, cat in self.card_cat.items() if cat in set(self.include)}
        self.card_name = {k: v for k, v in self.card_name.items() if k in keep}
        self.card_cat = {k: v for k, v in self.card_cat.items() if k in keep}
        self.card_comp = {k: v for k, v in self.card_comp.items() if k in keep}
        self.mult &= keep
        self.grow &= keep
        self.engine &= keep

    def early_ok(self, card: int, turn: int) -> bool:
        nm = self.card_name.get(card, "")
        win = EARLY_WINDOW.get(nm)
        return True if win is None else int(turn) <= int(win)


class CompBuyBias:
    """条件式买卡规则：已承诺阵容时"必须买"，否则只在开局对放大器软偏置。"""

    def __init__(self, cfg: Any = None, *, spec_path: str = "") -> None:
        self.mode = float(getattr(cfg, "comp_buy_bias", 0.0) or 0.0) if cfg is not None else 0.0
        if self.mode <= 0.0:
            self.mode = _env_on()
        self.enabled = bool(self.mode > 0.0)
        self.max_copies = int(getattr(cfg, "comp_buy_max_copies", 3) or 3) if cfg is not None else 3
        self.health_floor = float(getattr(cfg, "comp_buy_health_floor", 12.0) or 12.0) \
            if cfg is not None else 12.0
        self.opening_health = float(getattr(cfg, "comp_buy_opening_health", 20.0) or 20.0) \
            if cfg is not None else 20.0
        self.late_turn = int(getattr(cfg, "comp_buy_late_turn", 17) or 17) if cfg is not None else 17
        # 目标类别（默认只留乘算放大器 + 成长核心；ENGINE 类"买了也不滚"，v3 起移出）
        _inc = str(getattr(cfg, "comp_buy_include", "") or "").strip() if cfg is not None else ""
        if not _inc:
            _inc = (os.environ.get("HSBRSIM_COMP_BUY_INCLUDE", "") or "").strip() or "MULT,GROW"
        self.include = tuple(x.strip().upper() for x in _inc.split(",") if x.strip())
        # 开局阶段把 MULT 升级为"必须买"的门槛
        self.mult_force_health = float(getattr(cfg, "comp_buy_mult_force_health", 15.0) or 15.0) \
            if cfg is not None else 15.0
        self.mult_force_turn = int(getattr(cfg, "comp_buy_mult_force_turn", 12) or 12) \
            if cfg is not None else 12
        self.spec: Optional[CompSpec] = None
        if self.enabled:
            try:
                self.spec = CompSpec(
                    spec_path or str((getattr(cfg, "comp_cards", "")
                                      if cfg is not None else "") or ""),
                    include=self.include)
            except Exception:  # noqa: BLE001 - 规格缺失就整体关闭（不中断训练）
                self.enabled = False
                self.spec = None
        # 统计
        self.n_must = 0
        self.n_soft = 0
        self.n_release = 0
        self.n_hit = 0

    # ── 观测解析 ────────────────────────────────────────────────────────
    @staticmethod
    def _slice(cards: Any, sl: Any, n: int) -> list:
        c = np.asarray(cards).reshape(-1)
        base = int(sl.start)
        if base + n > c.size:
            return []
        return [int(c[base + i]) for i in range(int(n))]

    def _state(self, features: Any, cards: Any) -> Tuple[int, int, dict]:
        f = np.asarray(features, dtype=np.float32).reshape(-1)
        health = int(round(float(f[_HEALTH]) * GLOBAL_FIELD_SCALE["health"]))
        turn = int(round(float(f[_TURN]) * GLOBAL_FIELD_SCALE["turn"]))
        own: Dict[int, int] = {}
        for cid in (self._slice(cards, SLICE_CARD_BOARD, N_BOARD)
                    + self._slice(cards, SLICE_CARD_HAND, N_HAND)):
            if cid > 0:
                own[cid] = own.get(cid, 0) + 1
        return health, turn, own

    def _commitment(self, own: Dict[int, int]) -> Dict[str, int]:
        """own 里各阵容的核心张数（MULT 不计入承诺：它们跨阵容通用）。"""
        out: Dict[str, int] = {}
        for cid, n in own.items():
            if cid in (self.spec.mult if self.spec else set()):
                continue
            for comp in (self.spec.card_comp.get(cid) if self.spec else set()) or set():
                out[comp] = out.get(comp, 0) + n
        return out

    # ── 主逻辑 ──────────────────────────────────────────────────────────
    def rewrite(self, features: Any, cards: Any, mask: Any) -> Tuple[Any, bool]:
        if not self.enabled or self.spec is None:
            return mask, False
        m = np.asarray(mask)
        if m.ndim != 1:
            return mask, False
        shop = self._slice(cards, SLICE_CARD_SHOP, N_SHOP)
        if not shop:
            return mask, False
        # 商店里的**全部**合法买入（slot → 卡）；目标卡是其中的子集
        legal = {i: shop[i] for i in range(len(shop))
                 if shop[i] > 0 and int(A_BUY) + i < m.size and bool(m[int(A_BUY) + i])}
        buyable = {i: cid for i, cid in legal.items() if cid in self.spec.card_name}
        if not buyable:
            return mask, False
        health, turn, own = self._state(features, cards)

        # ── 恢复正常的通用条件 ──
        if health <= self.health_floor or turn > self.late_turn:
            self.n_release += 1
            return mask, False
        commit = self._commitment(own)
        # own 里已有 ≥2 个不同阵容的核心 ⇒ 已经成型在别的线上，不再强塞
        if len(commit) >= 2:
            self.n_release += 1
            return mask, False

        if commit:                                    # ① 已承诺：必须买
            comp = max(commit, key=lambda k: commit[k])
            slots = [i for i, cid in buyable.items()
                     if comp in (self.spec.card_comp.get(cid) or set())
                     and own.get(cid, 0) < self.max_copies
                     and self.spec.early_ok(cid, turn)]
            if not slots:
                return mask, False
            out = np.zeros_like(m)
            for i in slots:
                out[int(A_BUY) + i] = True
            self.n_must += 1
            self.n_hit += len(slots)
            self._protect(m, out, own, cards)
            return out, True

        # ② 开局：放大器（MULT）在门槛内**必须买**；成长核心（GROW）软偏置
        mult_slots = [i for i, cid in buyable.items()
                      if cid in self.spec.mult and own.get(cid, 0) < self.max_copies
                      and health > self.mult_force_health and turn <= self.mult_force_turn]
        if mult_slots:
            out = np.zeros_like(m)
            for i in mult_slots:
                out[int(A_BUY) + i] = True
            self.n_must += 1
            self.n_hit += len(mult_slots)
            self._protect(m, out, own, cards)
            return out, True
        if health < self.opening_health:
            self.n_release += 1
            return mask, False
        slots = [i for i, cid in buyable.items()
                 if cid in self.spec.grow
                 and own.get(cid, 0) < self.max_copies
                 and self.spec.early_ok(cid, turn)]
        if not slots:
            return mask, False
        out = np.array(m, copy=True)
        for i in legal:
            if i in slots:
                continue
            out[int(A_BUY) + i] = False
        self.n_soft += 1
        self.n_hit += len(slots)
        self._protect(m, out, own, cards)
        return out, True

    def _protect(self, m: Any, out: Any, own: Dict[int, int], cards: Any) -> None:
        """禁止卖掉 own 里的核心卡（棋盘槽）。"""
        board = self._slice(cards, SLICE_CARD_BOARD, N_BOARD)
        for i, cid in enumerate(board):
            if cid > 0 and cid in self.spec.card_name:
                a = int(A_SELL) + i
                if a < out.size:
                    out[a] = False

    def stats(self) -> dict:
        if not self.enabled:
            return {}
        return {"comp_buy_mode": float(self.mode),
                "comp_buy_threshold": float(100 * (len(self.spec.card_name) if self.spec else 0) / 123.0),
                "comp_buy_targets": float(len(self.spec.card_name) if self.spec else 0),
                "comp_must": float(self.n_must), "comp_soft": float(self.n_soft),
                "comp_release": float(self.n_release)}
