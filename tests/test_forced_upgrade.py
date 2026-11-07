"""强制升本守卫（forced_upgrade）的单元测试。"""
import numpy as np

from hsbg.az.train.forced_upgrade import ForcedUpgradeGuard, cheapest_shop_item
from hsbg.env.obs_std import GLOBAL_FIELD_INDEX, ITEM_COST, ITEM_PRESENT, SLICE_SHOP
from hsbg.env.action_space_std import A_UPGRADE


def _features(gold: float, upgrade: float, shop_costs) -> np.ndarray:
    f = np.zeros(3227, dtype=np.float32)
    f[GLOBAL_FIELD_INDEX["gold"]] = gold / 10.0
    f[GLOBAL_FIELD_INDEX["upgrade_price"]] = upgrade / 10.0
    base = SLICE_SHOP.start
    for i, c in enumerate(shop_costs):
        if c is None:
            continue
        f[base + i * 40 + ITEM_PRESENT] = 1.0
        f[base + i * 40 + ITEM_COST] = c / 5.0
    return f


def _cfg(on=True, margin=0.0):
    return type("C", (), {"forced_upgrade": on, "forced_upgrade_margin": margin})()


def _mask():
    m = np.zeros(274, dtype=bool)
    m[0] = True
    m[A_UPGRADE] = True
    m[10] = True
    return m


def test_cheapest_shop_item():
    assert cheapest_shop_item(_features(9, 7, [3, None, 2, 1])) == 1
    assert cheapest_shop_item(_features(9, 7, [None, None])) == 0


def test_force_when_affordable():
    g = ForcedUpgradeGuard(_cfg())
    out, forced = g.rewrite(_features(9, 7, [3, 2, 1]), _mask())
    assert forced and list(np.flatnonzero(out)) == [A_UPGRADE]
    _, forced2 = g.rewrite(_features(8, 7, [1]), _mask())
    assert not forced2                     # 严格大于：8 > 8 不成立
    g2 = ForcedUpgradeGuard(_cfg(margin=0.5))
    _, f3 = g2.rewrite(_features(9, 7, [1]), _mask())
    assert f3
    _, f4 = g2.rewrite(_features(8.2, 7, [1]), _mask())
    assert not f4


def test_no_force_when_upgrade_illegal_or_maxed():
    g = ForcedUpgradeGuard(_cfg())
    m = _mask()
    m[A_UPGRADE] = False
    _, forced = g.rewrite(_features(20, 7, [1]), m)
    assert not forced
    _, forced0 = g.rewrite(_features(20, 0, [1]), _mask())
    assert not forced0


def test_disabled_is_identity():
    g = ForcedUpgradeGuard(_cfg(on=False))
    assert not g.enabled
    m = _mask()
    out, forced = g.rewrite(_features(20, 7, [1]), m)
    assert not forced and out is m


def test_env_switch_enables(monkeypatch):
    monkeypatch.setenv("HSBRSIM_FORCE_UPGRADE", "1")
    assert ForcedUpgradeGuard(_cfg(on=False)).enabled
    monkeypatch.delenv("HSBRSIM_FORCE_UPGRADE")
    assert not ForcedUpgradeGuard(_cfg(on=False)).enabled
