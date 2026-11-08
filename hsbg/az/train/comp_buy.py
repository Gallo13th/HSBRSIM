"""复利阵容的「买卡偏置」（B11）：把 HSBG.md 里靠成长/乘算的阵容核心卡强行喂给策略。

动机（B08→B10 的结论）：
- B08 强制升本把 `tier≥5@t15` 从 7.7% 拉到 100%，但 6 本盘面**放大器卡位 0%**（人类 7%）；
- B09 人类行为模仿（BC）对复利无效（0.64% vs 基线 0.67%）；
- B10 终局强度辅助头把 t18/t20 强度拉高 44%/75%，但**"终局强度"这个标量可以用加法大卡满足**，
  依然不需要乘法结构。

所以 B11 直接在**行为分布**上动手：当商店里出现复利核心卡时，把"买其它卡"的分支屏蔽掉
（保留买目标卡 + 刷新/升本/结束回合等非购买动作），让轨迹里充满"买到核心卡之后怎么滚"的数据。
与"禁卡"无关，也不改奖励函数；关掉（`comp_buy_bias=0`）时是恒等函数。

规则：
1. 商店第 i 槽的卡 id 取观测卡块 ``cards[SLICE_CARD_SHOP.start + i]``（0=空槽；卡下标 = card_id+1）；
2. 若该卡属于目标集合且 ``A_BUY+i`` 合法 ⇒ 保留该动作；
3. **屏蔽其它购买动作**（其余商店槽的买入），其它动作（刷新/冻结/升本/技能/结束回合…）全部保留；
4. **屏蔽卖掉已上场的核心卡**（``A_SELL+i``，i 为棋盘槽），避免"买了就卖"；
5. 若商店里没有目标卡，则不改写（恒等）。

环境变量（评测侧与训练同源）：``HSBRSIM_COMP_BUY_BIAS=1``、``HSBRSIM_COMP_CARDS=<json>``。
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional, Set, Tuple

import numpy as np

from hsbg.env.action_space_std import A_BUY, A_SELL, N_SHOP
from hsbg.env.obs_std import N_BOARD, SLICE_CARD_BOARD, SLICE_CARD_SHOP

_DEFAULT_SPEC = "data/comp_cards.json"


def _env_on() -> bool:
    return (os.environ.get("HSBRSIM_COMP_BUY_BIAS", "") or "").strip() in ("1", "true", "yes")


def _env_spec() -> str:
    return (os.environ.get("HSBRSIM_COMP_CARDS", "") or "").strip() or _DEFAULT_SPEC


def load_bias_ids(path: str = "", *, include: Tuple[str, ...] = ("MULT", "GROW", "ENGINE")) -> Set[int]:
    """读取 ``data/comp_cards.json`` 的目标卡集合，返回**可直接与观测卡块比较**的下标
    （``cards`` 编码 = card_id + 1）。"""
    p = path or _env_spec()
    if not os.path.isabs(p):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), p)
    with open(p, encoding="utf-8") as f:
        spec = json.load(f)
    out: Set[int] = set()
    for key in include:
        ids = spec.get("%s_ids" % key.lower())
        if ids:
            out.update(int(x) for x in ids)
        else:                                   # 兼容只给 bias 字典的旧格式
            for v in ((spec.get("bias") or {}).get(key) or {}).values():
                out.update(int(x) for x in v)
    if not out:
        out = {int(x) for x in (spec.get("bias_ids") or [])}
    # 观测里的卡块编码是 ``cards[i] = card_id + 1``（0=空槽），规格文件存的是 card_id。
    # 这里统一 +1，返回"可直接与 cards 比较"的下标集合。
    return {int(x) + 1 for x in out}


class CompBuyBias:
    """商店里出现复利核心卡时，屏蔽其它购买并以"只买核心"的方式采集轨迹。"""

    def __init__(self, cfg: Any = None, *, spec_path: str = "") -> None:
        self.mod = float(getattr(cfg, "comp_buy_bias", 0.0) or 0.0) if cfg is not None else 0.0
        self.enabled = bool(self.mod > 0.0 or _env_on())
        self.targets: Set[int] = set()
        self.hit_decisions = 0      # 有目标卡在商店的决策数
        self.rewritten = 0          # 实际改写 mask 的次数
        self.bought = 0             # 目标卡被买下的次数（由 notes 统计）
        if self.enabled:
            try:
                self.targets = load_bias_ids(spec_path or str(
                    (getattr(cfg, "comp_cards", "") if cfg is not None else "") or ""))
            except Exception:  # noqa: BLE001 - 规格缺失就关闭（不中断训练）
                self.enabled = False
                self.targets = set()

    # ── 内部 ────────────────────────────────────────────────────────────
    @staticmethod
    def _shop_slots(cards: Any) -> list:
        c = np.asarray(cards).reshape(-1)
        base = int(SLICE_CARD_SHOP.start)
        if base + N_SHOP > c.size:
            return []
        return [int(c[base + i]) for i in range(int(N_SHOP))]

    @staticmethod
    def _board_slots(cards: Any) -> list:
        c = np.asarray(cards).reshape(-1)
        base = int(SLICE_CARD_BOARD.start)
        if base + N_BOARD > c.size:
            return []
        return [int(c[base + i]) for i in range(int(N_BOARD))]

    def rewrite(self, features: Any, cards: Any, mask: Any) -> Tuple[Any, bool]:
        """按规则改写 mask；返回 ``(mask, biased)``。关闭/无目标卡时原样返回。"""
        if not self.enabled or not self.targets:
            return mask, False
        m = np.asarray(mask)
        if m.ndim != 1:
            return mask, False
        shop = self._shop_slots(cards)
        if not shop:
            return mask, False
        hits = [i for i, cid in enumerate(shop)
                if cid > 0 and cid in self.targets and int(A_BUY) + i < m.size and bool(m[int(A_BUY) + i])]
        if not hits:
            return mask, False
        self.hit_decisions += 1
        out = np.array(m, copy=True)
        # 1) 屏蔽其它商店槽的购买
        for i in range(len(shop)):
            if i in hits:
                continue
            a = int(A_BUY) + i
            if a < out.size:
                out[a] = False
        # 2) 不要卖掉已上场的核心卡
        board = self._board_slots(cards)
        for i, cid in enumerate(board):
            if cid > 0 and cid in self.targets:
                a = int(A_SELL) + i
                if a < out.size:
                    out[a] = False
        if not bool(out.any()):          # 极端情况（全被屏蔽）→ 放弃改写
            return mask, False
        self.rewritten += 1
        return out, True

    def stats(self) -> dict:
        if not self.enabled:
            return {}
        return {"comp_buy_bias": float(self.mod),
                "comp_buy_targets": float(len(self.targets)),
                "comp_buy_hit": float(self.hit_decisions),
                "comp_buy_rewritten": float(self.rewritten)}
