"""动作序列辅助任务单测（``docs/ACTION_SEQUENCE_AUX.md``）。

覆盖（不依赖引擎；torch 相关用例在缺 torch 时 skip）：

1. **multi-hot 标签**：同回合多动作落到同一行、不同回合/座位/局互不串、uint8/shape；
2. **BCE 数值**：``seq_bce_loss`` 与手算 ``BCEWithLogits`` 一致（含权重）；
3. **ramp 边界**：解析/端点 clamp/线性插值/非法规格报错/``SeqCoefSchedule`` 进度；
4. **默认关闭（零影响）**：``seq_coef=0`` 时 ``ppo_losses`` 无 ``seq_loss`` 键、训练
   stats 与「无标签」完全一致、权重逐位相同、npz 不写 ``seq_target``；
5. **batch builder 缺字段**：无 ``seq_target`` 时批次正常构建（``seq_target=None``），
   形状不符时忽略；
6. **forced 排除**：forced 样本的标签怎么改都不影响 ``seq_loss``；
7. **seq 头**：``forward_aux`` 输出形状、训练能降低 ``seq_loss``、``coef=0`` 时 seq 头
   参数不动、checkpoint 往返保留 seq 头；
8. 入口脚本暴露 ``--seq-coef``。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.ppo import (
    BATCH_FIELDS,
    BATCH_OPTIONAL_FIELDS,
    CollectConfig,
    PPOConfig,
    build_batch_from_arrays,
    build_batch_from_records,
    masked_probs_np,
    pack_records_arrays,
    ppo_losses,
    train_ppo,
    value_from_rank_logits_np,
)
from hsbg.az.train.seq_aux import (
    SEQ_TARGET_KEY,
    SeqCoefSchedule,
    format_coef_ramp,
    parse_coef_ramp,
    ramp_coef,
    resolve_coef,
    seq_bce_loss,
    seq_targets_from_packed,
    seq_targets_from_records,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 默认关闭时必须与旧版本完全一致的 loss 键集合（顺序无关）
LEGACY_LOSS_KEYS = frozenset({
    "total", "policy_loss", "value_loss", "aux_pi_loss", "anchor_kl", "entropy",
    "approx_kl", "clip_frac", "ratio_mean", "illegal_prob_max", "adv_mean",
    "value_pred_mean",
})


def _needs_torch():
    return pytest.importorskip("torch")


# ── 1. 标签：turn 内动作 multi-hot ───────────────────────────────────────
def test_seq_targets_multi_hot_same_turn():
    recs = [
        # (seat 0, turn 0) 一回合内三个动作
        {"game_id": 0, "seat": 0, "turn": 0, "action": 3},
        {"game_id": 0, "seat": 0, "turn": 0, "action": 7},
        {"game_id": 0, "seat": 0, "turn": 0, "action": 200},
        # 同座位下一回合：只有 action 5
        {"game_id": 0, "seat": 0, "turn": 1, "action": 5},
        # 同局另一座位
        {"game_id": 0, "seat": 1, "turn": 0, "action": 9},
        # 另一局同 seat/turn/action：不能串到上一局
        {"game_id": 1, "seat": 0, "turn": 0, "action": 3},
    ]
    t = seq_targets_from_records(recs)
    assert t.shape == (len(recs), N_ACTIONS)
    assert t.dtype == np.uint8
    # 同回合的所有样本共享同一动作集合（含当前步及其后的动作）
    assert set(np.flatnonzero(t[0])) == {3, 7, 200}
    assert np.array_equal(t[0], t[1]) and np.array_equal(t[0], t[2])
    assert set(np.flatnonzero(t[3])) == {5}
    assert set(np.flatnonzero(t[4])) == {9}
    assert set(np.flatnonzero(t[5])) == {3}
    # 每行都标了本步实际执行的动作（loss 侧依赖这个不变量）
    for i, r in enumerate(recs):
        assert t[i, r["action"]] == 1
    # 行和 = 该回合动作数
    assert int(t[0].sum()) == 3 and int(t[3].sum()) == 1


def test_seq_targets_missing_turn_degrades_to_game_scope():
    """``turn`` 缺失记 -1：分组退化为「整局」（文档的已知局限，不静默出错）。"""
    recs = [
        {"game_id": 0, "seat": 0, "action": 1},
        {"game_id": 0, "seat": 0, "action": 2},
    ]
    t = seq_targets_from_records(recs)
    assert set(np.flatnonzero(t[0])) == {1, 2}
    assert np.array_equal(t[0], t[1])


def test_seq_targets_empty_and_invalid_action():
    empty = seq_targets_from_records([])
    assert empty.shape == (0, N_ACTIONS) and empty.dtype == np.uint8
    with pytest.raises(ValueError):
        seq_targets_from_records([{"game_id": 0, "seat": 0, "turn": 0,
                                   "action": N_ACTIONS}])


def test_seq_targets_from_packed_matches_records():
    recs = [
        {"game_id": 2, "seat": 0, "turn": 0, "action": 4, "features": np.zeros(OBS_FLOATS, np.float32),
         "cards": np.zeros(OBS_CARDS, np.int32), "mask": _onehot_mask(4),
         "old_logprob": -1.0, "value": 0.0, "rank": 1},
        {"game_id": 2, "seat": 0, "turn": 0, "action": 11, "features": np.zeros(OBS_FLOATS, np.float32),
         "cards": np.zeros(OBS_CARDS, np.int32), "mask": _onehot_mask(11),
         "old_logprob": -1.0, "value": 0.0, "rank": 1},
    ]
    packed = pack_records_arrays(recs, seq_aux=True)
    assert SEQ_TARGET_KEY in packed
    assert np.array_equal(packed[SEQ_TARGET_KEY], seq_targets_from_records(recs))
    assert np.array_equal(seq_targets_from_packed(packed), packed[SEQ_TARGET_KEY])


# ── 2. BCE 数值 ─────────────────────────────────────────────────────────
def _bce_ref(z: float, t: float) -> float:
    """BCEWithLogits 的标量定义：max(z,0) - z*t + log(1+exp(-|z|))。"""
    return max(z, 0.0) - z * t + float(np.log1p(np.exp(-abs(z))))


def test_seq_bce_loss_matches_manual():
    torch = _needs_torch()
    logits = torch.tensor([[0.0, 2.0], [1.0, -1.0]], dtype=torch.float32)
    target = torch.tensor([[1.0, 0.0], [0.0, 1.0]], dtype=torch.float32)
    got = float(seq_bce_loss(logits, target))
    rows = [[_bce_ref(0.0, 1.0), _bce_ref(2.0, 0.0)],
            [_bce_ref(1.0, 0.0), _bce_ref(-1.0, 1.0)]]
    expect = float(np.mean([np.mean(r) for r in rows]))
    assert got == pytest.approx(expect, rel=1e-5, abs=1e-6)
    # 权重只看选中行
    w = torch.tensor([1.0, 0.0])
    assert float(seq_bce_loss(logits, target, weight=w)) == pytest.approx(
        float(np.mean(rows[0])), rel=1e-5, abs=1e-6)
    # 全 0 权重不产生 NaN
    assert float(seq_bce_loss(logits, target, weight=torch.zeros(2))) == 0.0


# ── 3. ramp ─────────────────────────────────────────────────────────────
def test_parse_coef_ramp_and_interpolation():
    pts = parse_coef_ramp("0.02@0,0.05@0.5")
    assert pts == [(0.0, pytest.approx(0.02)), (0.5, pytest.approx(0.05))]
    assert ramp_coef(pts, 0.0) == pytest.approx(0.02)
    assert ramp_coef(pts, 0.25) == pytest.approx(0.035)
    assert ramp_coef(pts, 0.5) == pytest.approx(0.05)
    assert ramp_coef(pts, 0.75) == pytest.approx(0.05)   # 末端 clamp
    assert ramp_coef(pts, -1.0) == pytest.approx(0.02)   # 起点 clamp
    assert ramp_coef(pts, 2.0) == pytest.approx(0.05)
    assert ramp_coef(pts, float("nan")) == pytest.approx(0.02)
    # 乱序输入内部排序；同进度保留后者
    assert parse_coef_ramp("0.05@0.5,0.02@0") == pts
    assert parse_coef_ramp("0.01@0.5,0.02@0.5") == [(0.5, pytest.approx(0.02))]
    # 单点 / 空
    assert ramp_coef(parse_coef_ramp("0.03@0.7"), 0.0) == pytest.approx(0.03)
    assert parse_coef_ramp("") == [] and ramp_coef([], 0.5) == 0.0
    assert format_coef_ramp(pts) == "0.02@0.000,0.05@0.500"


def test_parse_coef_ramp_rejects_bad_specs():
    for spec in ("0.02", "abc@0", "0.02@1.5", "-0.1@0", "0.02@nan", ",", "@0"):
        with pytest.raises(ValueError):
            parse_coef_ramp(spec)


def test_resolve_coef_and_schedule_bounds():
    assert resolve_coef(0.7, [], 0.5) == pytest.approx(0.7)
    assert resolve_coef(0.0, parse_coef_ramp("0.02@0,0.05@1"), 0.5) == pytest.approx(0.035)
    # 无预算：进度恒 0（停在第一个控制点），describe 显式标注
    sched = SeqCoefSchedule.from_spec(0.0, "0.02@0,0.05@0.5", total_decisions=0.0)
    assert sched.enabled is True
    assert sched.progress(10 ** 9) == 0.0
    assert sched.coef(10 ** 9) == pytest.approx(0.02)
    assert sched.describe()["ramp_progress_at_zero"] is True
    # 有预算：按 decisions 比例
    sched = SeqCoefSchedule.from_spec(0.0, "0.02@0,0.05@0.5", total_decisions=1000.0)
    assert sched.progress(250) == pytest.approx(0.25)
    assert sched.coef(250) == pytest.approx(0.035)
    assert sched.coef(10 ** 6) == pytest.approx(0.05)
    # 常数系数（无 ramp）
    const = SeqCoefSchedule.from_spec(0.02, "", total_decisions=100.0)
    assert const.enabled is True and const.coef(0) == pytest.approx(0.02)
    assert const.coef(100) == pytest.approx(0.02)
    # 全 0 = 关闭
    off = SeqCoefSchedule.from_spec(0.0, "", total_decisions=100.0)
    assert off.enabled is False


def test_ppo_config_validates_seq_fields():
    assert PPOConfig().seq_coef == 0.0 and PPOConfig().seq_coef_ramp == ""
    assert PPOConfig(seq_coef=0.02, seq_coef_ramp="0.02@0,0.05@0.5").seq_coef == pytest.approx(0.02)
    with pytest.raises(ValueError):
        PPOConfig(seq_coef=-0.1)
    with pytest.raises(ValueError):
        PPOConfig(seq_coef_ramp="0.02")


# ── 4/5. 默认关闭 + batch builder 缺字段 ────────────────────────────────
def _onehot_mask(action: int) -> np.ndarray:
    mask = np.zeros(N_ACTIONS, dtype=bool)
    mask[int(action)] = True
    return mask


def _synthetic_records(*, seed: int = 0, game_id: int = 0, seats=(0,),
                       turns=(0, 1), actions=None) -> list:
    """最小合成记录：每 (seat, turn) 一个动作，足够跑 batch builder / loss。"""
    rng = np.random.default_rng(seed)
    recs = []
    for seat in seats:
        for turn in turns:
            act = int(rng.integers(0, N_ACTIONS)) if actions is None else int(actions[turn])
            recs.append({
                "features": rng.normal(size=OBS_FLOATS).astype(np.float32),
                "cards": np.zeros(OBS_CARDS, dtype=np.int32),
                "mask": _onehot_mask(act),
                "action": act,
                "old_logprob": -1.0,
                "value": 0.0,
                "target_pi": None,
                "rank": int(seat) + 1,
                "seat": int(seat),
                "game_id": int(game_id),
                "turn": int(turn),
            })
    return recs


def test_collect_config_default_seq_off():
    assert CollectConfig().seq_aux is False


def test_batch_fields_unchanged_and_optional_only():
    assert BATCH_FIELDS == (
        "features", "cards", "masks", "actions", "old_logprobs", "values", "rewards",
        "dones", "advantages", "returns", "seats", "game_ids", "ranks", "turns",
        "target_pi", "has_pi", "episode_ids", "forced",
    )
    assert BATCH_OPTIONAL_FIELDS == (SEQ_TARGET_KEY,)


def test_build_batch_from_records_seq_off_has_no_labels(tmp_path):
    recs = _synthetic_records(seats=(0, 1), turns=(0, 1, 2))
    batch = build_batch_from_records(recs)
    assert batch.seq_target is None
    assert "seq_aux" not in batch.meta
    assert batch.validate() == []
    path = os.path.join(tmp_path, "b.npz")
    batch.save(path)
    with np.load(path) as z:
        assert f"arr_{SEQ_TARGET_KEY}" not in z.files
    # summary 不带 seq 字段
    assert "seq_target_rate" not in batch.summary()


def test_build_batch_from_records_seq_on_labels_and_validation(tmp_path):
    # seat 0：turn0 两个动作（3, 7），turn1 一个动作（9）
    recs = _synthetic_records(seats=(0,), turns=(0, 0, 1))
    recs[0]["action"], recs[0]["mask"] = 3, _onehot_mask(3)
    recs[1]["action"], recs[1]["mask"] = 7, _onehot_mask(7)
    recs[2]["action"], recs[2]["mask"] = 9, _onehot_mask(9)
    batch = build_batch_from_records(recs, seq_aux=True)
    assert batch.seq_target is not None
    assert batch.seq_target.dtype == np.uint8
    assert batch.validate() == [], batch.validate()
    # 同 turn 的两条样本标签一致且是 {3,7}；turn1 是 {9}
    by_turn = {}
    for i, t in enumerate(batch.turns):
        by_turn.setdefault(int(t), []).append(i)
    for idx in by_turn[0]:
        assert set(np.flatnonzero(batch.seq_target[idx])) == {3, 7}
    for idx in by_turn[1]:
        assert set(np.flatnonzero(batch.seq_target[idx])) == {9}
    assert batch.meta.get("seq_aux") is True
    assert batch.summary()["seq_target_rate"] == pytest.approx(1.0)
    # npz 往返保留标签
    path = os.path.join(tmp_path, "b2.npz")
    batch.save(path)
    loaded = type(batch).load(path)
    assert np.array_equal(loaded.seq_target, batch.seq_target)
    assert loaded.validate() == []


def test_batch_validate_catches_bad_seq_target():
    recs = _synthetic_records(seats=(0,), turns=(0,))
    batch = build_batch_from_records(recs, seq_aux=True)
    bad = copy.deepcopy(batch)
    bad.seq_target = np.zeros_like(batch.seq_target)   # 不标本步动作
    errs = bad.validate()
    assert any("seq_target" in e for e in errs), errs
    bad2 = copy.deepcopy(batch)
    bad2.seq_target = np.full_like(batch.seq_target, 2)
    assert any("seq_target" in e for e in bad2.validate())


def test_build_batch_from_arrays_tolerates_missing_seq_target():
    recs = _synthetic_records(seats=(0, 1), turns=(0, 1))
    packed_off = pack_records_arrays(recs)          # 旧调用方式
    assert SEQ_TARGET_KEY not in packed_off
    b_off = build_batch_from_arrays(packed_off)
    assert b_off.seq_target is None
    assert b_off.validate() == []

    packed_on = pack_records_arrays(recs, seq_aux=True)
    assert SEQ_TARGET_KEY in packed_on
    b_on = build_batch_from_arrays(packed_on)
    assert b_on.seq_target is not None and b_on.validate() == []

    # 形状不符 -> 忽略（不炸）
    bad = dict(packed_off)
    bad[SEQ_TARGET_KEY] = np.zeros((len(recs), 10), dtype=np.uint8)
    assert build_batch_from_arrays(bad).seq_target is None


# ── 6. coef=0：无 seq 字段、无影响 ──────────────────────────────────────
def _batch_from_model(model, *, seed: int = 3, seq_aux: bool = False, n_games: int = 1,
                      decisions_per_seat: int = 3):
    """用当前模型自己的 masked softmax 生成动作/old_logprob，保证 ratio 起点=1。"""
    torch = _needs_torch()
    rng = np.random.default_rng(seed)
    model.eval()
    records = []
    for g in range(n_games):
        for seat in range(2):
            rank = int((g * 3 + seat) % 8) + 1
            for t in range(decisions_per_seat):
                features = rng.normal(size=OBS_FLOATS).astype(np.float32)
                cards = np.zeros(OBS_CARDS, dtype=np.int32)
                mask = np.zeros(N_ACTIONS, dtype=bool)
                legal = rng.choice(N_ACTIONS, size=int(rng.integers(3, 8)), replace=False)
                mask[legal] = True
                x = torch.from_numpy(features.reshape(1, -1))
                c = torch.from_numpy(cards.astype(np.int64).reshape(1, -1))
                with torch.no_grad():
                    out = model(x, c)
                probs = masked_probs_np(out[0].numpy()[0], mask)
                probs = probs / max(float(probs.sum()), 1e-12)
                action = int(rng.choice(N_ACTIONS, p=probs))
                records.append({
                    "features": features, "cards": cards, "mask": mask,
                    "action": action,
                    "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
                    "value": float(value_from_rank_logits_np(out[1].numpy()[0])[0]),
                    "target_pi": None, "rank": rank, "seat": seat,
                    "game_id": g, "turn": t,
                })
    return build_batch_from_records(records, step_penalty=1e-3, seq_aux=seq_aux)


def test_seq_coef_zero_adds_no_field_and_no_gradient():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    torch.manual_seed(0)
    model = build_net(16, seq_head=True)      # 即使模型带 seq 头，coef=0 也完全不动它
    batch = _batch_from_model(model, seq_aux=True)
    out = ppo_losses(model, batch, PPOConfig(pi_coef=0.0))
    assert "seq_loss" not in out
    assert frozenset(out) == LEGACY_LOSS_KEYS
    # seq 头不参与前向 -> 无梯度
    model.zero_grad(set_to_none=True)
    out["total"].backward()
    assert model.seq_head.weight.grad is None
    # 标签存在但 coef=0：训练 stats 与无标签批次完全一致（含 config 回显）
    torch.manual_seed(0)
    m0 = build_net(16, seq_head=True)
    per_a = _synthetic_records(seed=0, seats=(0, 1), turns=(0, 1))
    records_like = _synthetic_records(seed=0, seats=(0, 1), turns=(0, 1))
    b_plain = build_batch_from_records(per_a, step_penalty=1e-3)
    b_lab = build_batch_from_records(records_like, step_penalty=1e-3, seq_aux=True)
    cfg = PPOConfig(epochs=1, minibatch=2, seed=0, target_kl=10.0, pi_coef=0.0)
    m1, m2 = copy.deepcopy(m0), copy.deepcopy(m0)
    s1 = train_ppo(m1, b_plain, cfg)
    s2 = train_ppo(m2, b_lab, cfg)
    assert s1["updates"] == s2["updates"] and s1["samples"] == s2["samples"]

    def _metrics(stats):
        # 去掉纯计时字段后逐项比较（其余浮点必须逐位一致）
        return [{k: v for k, v in r.items() if k != "elapsed_s"} for r in stats["epochs"]]

    assert _metrics(s1) == _metrics(s2)
    assert s1["config"] == s2["config"]
    assert "seq_loss" not in s1 and "seq_coef" not in s1
    for p, q in zip(m1.parameters(), m2.parameters()):
        assert torch.equal(p, q)


def test_seq_loss_ignores_forced_samples():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    torch.manual_seed(0)
    model = build_net(16, seq_head=True)
    batch = _batch_from_model(model, seq_aux=True)
    batch.forced = np.zeros(len(batch), dtype=bool)
    batch.forced[[0, 2]] = True
    cfg = PPOConfig(pi_coef=0.0, seq_coef=0.5)
    base = float(ppo_losses(model, batch, cfg)["seq_loss"])
    # forced 行的标签改成全 1（完全不同）-> seq_loss 不变
    alt = copy.deepcopy(batch)
    alt.seq_target[batch.forced] = 1
    assert float(ppo_losses(model, alt, cfg)["seq_loss"]) == pytest.approx(base, rel=1e-6)
    # 非 forced 行标签清零（被 has_target 排除）且 forced 行全 1 -> 权重全 0 -> 0
    empt = copy.deepcopy(batch)
    empt.seq_target[~batch.forced] = 0
    empt.seq_target[batch.forced] = 1
    assert float(ppo_losses(model, empt, cfg)["seq_loss"]) == 0.0
    # 手工核对：只对非 forced 行平均
    import torch as _t
    tgt = _t.from_numpy(batch.seq_target.astype(np.float32))
    mask_rows = _t.from_numpy((~batch.forced).astype(np.float32))
    with _t.no_grad():
        _l, _r, _s, seq_logits = model.forward_aux(
            _t.from_numpy(batch.features), _t.from_numpy(batch.cards.astype(np.int64)),
            _t.from_numpy(batch.masks))
        expect = float(seq_bce_loss(seq_logits, tgt, weight=mask_rows))
    assert base == pytest.approx(expect, rel=1e-5, abs=1e-6)


def test_train_ppo_seq_coef_reports_and_trains_head():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    torch.manual_seed(0)
    model = build_net(32, seq_head=True)
    batch = _batch_from_model(model, seq_aux=True)
    before = model.seq_head.weight.detach().clone()
    cfg = PPOConfig(epochs=2, minibatch=4, lr=3e-3, seed=0, target_kl=10.0,
                    pi_coef=0.0, seq_coef=0.5, seq_coef_ramp="0.02@0,0.05@0.5")
    init_loss = float(ppo_losses(model, batch, cfg)["seq_loss"])   # 训练前基线
    assert init_loss > 0.0
    stats = train_ppo(model, batch, cfg)
    assert stats["seq_coef"] == pytest.approx(0.5)
    assert stats["seq_coef_ramp"] == "0.02@0,0.05@0.5"
    assert "seq_loss" in stats and np.isfinite(stats["seq_loss"])
    assert all("seq_loss" in r for r in stats["epochs"])
    # seq 头确实被更新（有梯度且进了 optimizer）
    assert not torch.equal(before, model.seq_head.weight.detach())
    assert model.seq_head.weight.grad is not None
    # total 里确实含 seq 项：coef=0 时 total 明显不同
    out_seq = ppo_losses(model, batch, PPOConfig(pi_coef=0.0, seq_coef=0.5))
    out_off = ppo_losses(model, batch, PPOConfig(pi_coef=0.0, seq_coef=0.0))
    delta = float(out_seq["total"]) - float(out_off["total"])
    assert delta == pytest.approx(0.5 * float(out_seq["seq_loss"]), rel=1e-5, abs=1e-6)


def test_seq_bce_loss_is_minimizable():
    """seq 头目标可达：直接对 logits 做梯度下降能把 BCE 压到接近 0（数值层面）。"""
    torch = _needs_torch()
    target = torch.zeros(4, N_ACTIONS)
    target[:, [3, 7, 200]] = 1.0
    logits = torch.zeros(4, N_ACTIONS, requires_grad=True)
    opt = torch.optim.Adam([logits], lr=0.5)
    losses = []
    for _ in range(30):
        opt.zero_grad(set_to_none=True)
        loss = seq_bce_loss(logits, target)
        loss.backward()
        opt.step()
        losses.append(float(loss.detach()))
    assert losses[0] == pytest.approx(float(np.log(2.0)), abs=1e-5)   # 全 0 logits = log2
    assert losses[-1] < 0.05
    assert losses[-1] < losses[0]


def test_seq_loss_zero_when_batch_has_no_labels():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    torch.manual_seed(0)
    model = build_net(16, seq_head=True)
    batch = _batch_from_model(model, seq_aux=False)     # 无标签
    out = ppo_losses(model, batch, PPOConfig(pi_coef=0.0, seq_coef=0.5))
    assert float(out["seq_loss"]) == 0.0
    assert np.isfinite(float(out["total"]))


# ── 7. seq 头前向 / checkpoint ─────────────────────────────────────────
def test_model_forward_aux_shapes_and_checkpoint_roundtrip(tmp_path):
    torch = _needs_torch()
    from hsbg.az.train.model import build_net, load_checkpoint, save_checkpoint

    torch.manual_seed(0)
    model = build_net(16, seq_head=True)
    x = torch.randn(3, OBS_FLOATS)
    c = torch.zeros(3, OBS_CARDS, dtype=torch.long)
    mask = torch.zeros(3, N_ACTIONS, dtype=torch.bool)
    mask[:, [0, 3]] = True
    logits, rank_logits, scalar, seq = model.forward_aux(x, c, mask)
    assert tuple(logits.shape) == (3, N_ACTIONS)
    assert tuple(rank_logits.shape) == (3, 8)
    assert scalar is None
    assert tuple(seq.shape) == (3, N_ACTIONS)
    # 老接口不变：forward 仍是 2 元组
    out = model(x, c)
    assert isinstance(out, tuple) and len(out) == 2

    path = os.path.join(tmp_path, "seq.pt")
    save_checkpoint(model, path, meta={"arch": "tiny", "hidden": 16})
    loaded, meta = load_checkpoint(path)
    assert bool(meta.get("seq_head")) is True
    assert loaded.seq_head is not None
    assert torch.equal(loaded.seq_head.weight, model.seq_head.weight)

    path2 = os.path.join(tmp_path, "plain.pt")
    plain = build_net(16)
    assert plain.forward_aux(x, c, mask)[3] is None
    save_checkpoint(plain, path2, meta={"arch": "tiny", "hidden": 16})
    loaded2, meta2 = load_checkpoint(path2)
    assert bool(meta2.get("seq_head")) is False and loaded2.seq_head is None


def test_entity_forward_aux():
    pytest.importorskip("hsbg_engine")
    torch = _needs_torch()
    from hsbg.az.train.entity_model import build_entity_net

    torch.manual_seed(0)
    model = build_entity_net(d_model=32, n_layers=1, n_heads=4, seq_head=True)
    x = torch.randn(2, OBS_FLOATS)
    c = torch.zeros(2, OBS_CARDS, dtype=torch.long)
    mask = torch.zeros(2, N_ACTIONS, dtype=torch.bool)
    mask[:, [0, 8]] = True
    logits, rank_logits, value, seq = model.forward_aux(x, c, mask)
    assert tuple(logits.shape) == (2, N_ACTIONS)
    assert tuple(seq.shape) == (2, N_ACTIONS)
    assert value is not None
    assert model(x, c, mask)[0].shape == logits.shape


# ── 8. 入口脚本暴露参数 ────────────────────────────────────────────────
def test_entry_scripts_expose_seq_flags():
    for script in ("scripts/train_az_ppo.py", "scripts/train_entity_sync.py"):
        proc = subprocess.run([sys.executable, os.path.join(ROOT, script), "--help"],
                              cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert proc.returncode == 0, proc.stderr
        assert "--seq-coef" in proc.stdout, script
        assert "--seq-coef-ramp" in proc.stdout, script


def test_json_roundtrip_of_stats_with_seq():
    """stats 必须可 JSON 序列化（history.jsonl 直接写）。"""
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    torch.manual_seed(0)
    model = build_net(8, seq_head=True)
    batch = _batch_from_model(model, seq_aux=True)
    stats = train_ppo(model, batch, PPOConfig(epochs=1, minibatch=4, seed=0,
                                              target_kl=10.0, pi_coef=0.0,
                                              seq_coef=0.1))
    assert json.loads(json.dumps(stats))["seq_coef"] == pytest.approx(0.1)
