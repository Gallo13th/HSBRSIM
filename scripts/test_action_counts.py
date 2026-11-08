"""同 trace 两侧计数相等（action_counts 统一口径的回归测试）。"""
from __future__ import annotations

from hsbg.az.train.action_counts import classify, count_actions


def test_classify_basic() -> None:
    assert classify(1) == "roll"
    assert classify(3) == "upgrade"
    assert classify(8) == "buy"
    assert classify(15) == "buy"
    assert classify(16) == "sell"
    assert classify(23) == "sell"
    assert classify(4) == "hero_power"
    assert classify(45) == "choose"
    assert classify(46) == "play"
    assert classify(0) == "end"


def test_same_trace_counts_identical() -> None:
    """训练侧 batch.actions（整数列表）与评估侧 turns.actions（取 a 字段）必须一致。"""
    import random

    rng = random.Random(7)
    trace = [int(rng.choice([1, 3, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 45, 46, 47, 0])) for _ in range(1000)]
    train_side = count_actions(trace)
    eval_side = count_actions([int(x) for x in trace])  # collector 记录为 {"a": x}，取 a 后同一函数
    assert train_side == eval_side
    assert train_side["sell"] > 0 and train_side["roll"] > 0 and train_side["buy"] > 0
