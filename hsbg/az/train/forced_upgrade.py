"""强制升本守卫（forced upgrade）：用一条**硬规则**生成"贪本"轨迹，绕开探索难题。

规则（`docs/B08_DESIGN.md §A'`，B10 起加"到 5 本即停"）：
    本回合任一决策点，若**当前 tier < max_tier（默认 5）** 且
        ``gold > upgrade_price + 商店里当下最便宜的商品价格``
    且动作为合法的「升级」（``A_UPGRADE``），则**只允许升级**（把 mask 其余位清零）。

到 ``max_tier``（默认 5）之后不再强制：规则只负责"把模型送上 5 本"，
5 本之后怎么滚（升 6、买核心、roll）交给策略自己决定——避免规则把"复利"一起
焊死成"无脑升 6 本"。

为什么用它：低本稳健运营是当前策略的局部最优；而"早升本"的收益在 13+ 回合后才兑现，
PPO 的 GAE 视野 + 稀有高本数据都不足以把这个方向探索出来（见
`docs/OBS_CREDIT_DISCUSSION.md` 命题 1/5）。这条规则直接**把行为拉到另一条轨迹分布上**，
用真实对局数据去回答"高本到底值不值"。

口径与实现：
- 只用**观测**（不读 ``player_json``，避免每决策多一次 JSON 开销）：
  ``gold``/``upgrade_price`` 取 global 块（÷10 归一），商店最便宜价取 ``shop_items`` 块的
  ``ITEM_COST``（引擎里 ``cost/5.0`` 归一，回乘 5 还原）。
- ``A_UPGRADE = 3``（``hsbg/env/action_space_std.py``）。
- 默认关闭：``cfg.forced_upgrade=False`` 且环境变量 ``HSBRSIM_FORCE_UPGRADE`` 不为 ``1`` 时，
  :meth:`rewrite` 是恒等函数（旧路径逐位不变）。
"""

from __future__ import annotations

import os
from typing import Any, Tuple

import numpy as np

from hsbg.env.obs_std import (
    GLOBAL_FIELD_INDEX,
    ITEM_COST,
    ITEM_PRESENT,
    SLICE_SHOP,
    N_SHOP,
    ITEM_F,
)
from hsbg.env.action_space_std import A_UPGRADE

#: global 字段的归一化除数（与 `obs_std.GLOBAL_FIELD_SCALE` 一致）
_GOLD_SCALE = 10.0
_UPGRADE_SCALE = 10.0
#: item 价格的归一化除数（引擎 `obs.rs::push_item`: `cost as f32 / 5.0`）
_COST_SCALE = 5.0

_GOLD = int(GLOBAL_FIELD_INDEX["gold"])
_UPGRADE = int(GLOBAL_FIELD_INDEX["upgrade_price"])
_TIER = int(GLOBAL_FIELD_INDEX["tier"])
#: tier 的归一化除数（`obs_std.GLOBAL_FIELD_SCALE["tier"]`）
_TIER_SCALE = 6.0

#: item 子块的跨距（`shop_items` 是 N_SHOP × ITEM_F 的扁平块）
_ITEM_STRIDE = int(ITEM_F)


def cheapest_shop_item(features: Any) -> int:
    """商店里当下最便宜**存在**商品的价格（金币）；没有商品返回 0。"""
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    base = int(SLICE_SHOP.start)
    best = 0
    for i in range(int(N_SHOP)):
        off = base + i * _ITEM_STRIDE
        if off + _ITEM_STRIDE > f.size:
            break
        if float(f[off + int(ITEM_PRESENT)]) <= 0.0:
            continue
        cost = int(round(float(f[off + int(ITEM_COST)]) * _COST_SCALE))
        if cost <= 0:
            continue
        best = cost if best == 0 else min(best, cost)
    return best


def _env_enabled() -> bool:
    return (os.environ.get("HSBRSIM_FORCE_UPGRADE", "") or "").strip() in ("1", "true", "yes")


def _env_max_tier() -> int:
    """``HSBRSIM_FORCE_UPGRADE_MAX_TIER``（评测侧与训练同源）；缺省 5，<=0 表示不限。"""
    raw = (os.environ.get("HSBRSIM_FORCE_UPGRADE_MAX_TIER", "") or "").strip()
    if not raw:
        return 5
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 5


class ForcedUpgradeGuard:
    """把「买得起升级 + 最便宜商品」时的动作强制成升级。"""

    def __init__(self, cfg: Any = None) -> None:
        cfg_en = bool(getattr(cfg, "forced_upgrade", False)) if cfg is not None else False
        self.enabled = bool(cfg_en or _env_enabled())
        self.margin = float(getattr(cfg, "forced_upgrade_margin", 0.0) or 0.0) \
            if cfg is not None else 0.0
        _cfg_mt = getattr(cfg, "forced_upgrade_max_tier", None) if cfg is not None else None
        self.max_tier = int(_env_max_tier() if _cfg_mt is None else int(_cfg_mt))
        self.forced = 0          # 被强制升级的决策数
        self.skipped_high_tier = 0   # 已到 max_tier 而放行的次数（诊断用）
        self.checks = 0          # 满足条件但升级非法的次数（诊断用）

    # ── 判定 ────────────────────────────────────────────────────────────
    def should_force(self, features: Any) -> bool:
        f = np.asarray(features, dtype=np.float32).reshape(-1)
        if f.size <= max(_GOLD, _UPGRADE):
            return False
        # 金币/升级价在游戏里都是整数：先取整，避免 float32 归一化误差
        # （例如 8/10*10 = 8.0000001 会把「8 > 8」误判为真）
        if int(self.max_tier) > 0:
            tier = int(round(float(f[_TIER]) * _TIER_SCALE))
            if tier >= int(self.max_tier):
                return False                  # 已到上限本数：不再强制（交给策略）
        gold = int(round(float(f[_GOLD]) * _GOLD_SCALE))
        upgrade = int(round(float(f[_UPGRADE]) * _UPGRADE_SCALE))
        if upgrade <= 0.0:
            return False                      # 已到最高本 / 无升级项
        cheapest = cheapest_shop_item(f)
        need = upgrade + (cheapest if cheapest > 0 else 0) + float(self.margin)
        return gold > need

    def rewrite(self, features: Any, mask: Any) -> Tuple[Any, bool]:
        """按规则改写 mask；返回 ``(mask, forced)``。关闭时原样返回。"""
        if not self.enabled:
            return mask, False
        m = np.asarray(mask)
        if m.ndim != 1 or int(A_UPGRADE) >= m.size:
            return mask, False
        if not bool(m[int(A_UPGRADE)]):
            return mask, False
        if not self.should_force(features):
            return mask, False
        out = np.zeros_like(m)
        out[int(A_UPGRADE)] = True
        self.forced += 1
        return out, True

    def stats(self) -> dict:
        if not self.enabled:
            return {}
        return {"forced_upgrade": int(self.forced),
                "forced_upgrade_margin": float(self.margin),
                "forced_upgrade_max_tier": int(self.max_tier)}
