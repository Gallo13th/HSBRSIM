"""`scripts/quality_monitor.py` 的载体审计契约：pending 目标候选的读取。

回归的 bug：引擎 `Pending::Target` 序列化键是 **`targets`**
（`rust/crates/hsbg-engine/src/debug.rs`），而脚本读 `pending["options"]`
⇒ 候选列表恒为空 ⇒ `casts_on_carrier_mean` 恒为 0（`docs/ECONOMY_SANDBOX.md` §9.7）。
这里用两种 pending 结构（新 `targets` / 旧 `options`）锁住兼容读取。
"""

from __future__ import annotations

import scripts.quality_monitor as Q


def test_pending_target_engine_targets_key():
    """引擎当前格式：`{"kind": "target", "targets": [eid, ...]}`（int 列表）。"""
    pend = {"kind": "target", "targets": [41, 42, 7]}
    assert Q._pending_target_eids(pend) == [41, 42, 7]


def test_pending_target_legacy_options_key():
    """旧数据格式：`options` 是带 `eid` 的 dict 列表，按动作下标对齐。"""
    pend = {"kind": "target", "options": [{"eid": 11}, {"eid": 12}]}
    assert Q._pending_target_eids(pend) == [11, 12]


def test_pending_target_mixed_and_invalid_elements():
    """targets 里混入不可解析元素时留 None（不会被误判命中）。"""
    pend = {"kind": "target", "targets": [3, {"eid": 4}, "bad"]}
    assert Q._pending_target_eids(pend) == [3, 4, None]


def test_pending_target_prefers_targets_over_options():
    """两种键同时存在时**先读 targets**（引擎新口径优先）。"""
    pend = {"kind": "target", "targets": [5], "options": [{"eid": 99}]}
    assert Q._pending_target_eids(pend) == [5]


def test_pending_target_non_target_kinds_are_none():
    """非目标选择（discover / hero / 无 pending）不参与对载体施法审计。"""
    assert Q._pending_target_eids({"kind": "discover", "options": [{"eid": 1}]}) is None
    assert Q._pending_target_eids({"kind": "hero", "options": []}) is None
    assert Q._pending_target_eids({}) is None
    assert Q._pending_target_eids({"kind": "target"}) is None


def test_pending_target_empty_targets():
    """是目标选择但没有候选：返回空列表（与 None 区分）。"""
    assert Q._pending_target_eids({"kind": "target", "targets": []}) == []


def test_pending_target_action_index_maps_to_eid():
    """动作 30..45 -> 候选下标 -> eid：命中载体 eid 才计数（与 _play 的判定同公式）。"""
    pend = {"kind": "target", "targets": [100, 200, 300]}
    eids = Q._pending_target_eids(pend)
    carrier_eids = {200}
    hits = [30 + i for i, eid in enumerate(eids) if eid in carrier_eids]
    assert hits == [31]
