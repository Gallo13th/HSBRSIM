"""upgrade 子集 DPO 损失（``hsbg.az.train.dpo_upgrade``）单测。

覆盖：
1. ``dpo_pair_loss`` 手算对照（固定 logits + 限定 mask）；
2. ``argmax == chosen`` 的样本被跳过（只对接受样本取均值、接受率正确）；
3. mask 处理：非法位置即使 logits 很大也不会被选成 rejected，也不影响 logp；
4. 空样本返回 0、接受率 0；
5. ``beta`` 生效（损失 = ``log(1+exp(beta))`` 随 beta 单调增）；
6. ``load_upgrade_samples`` 只保留 upgrade + MMR 合格样本，标签恒为 3。
"""

from __future__ import annotations

import gzip
import json
import math

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.dpo_upgrade import (
    UPGRADE_ACTION,
    UpgradeSamples,
    dpo_pair_loss,
    load_upgrade_samples,
    masked_policy_logprobs,
)

torch = pytest.importorskip("torch")


# ── 固定 logits 的假模型（只吃 features 行数，返回预置 [B,245]）────────────
class _FixedNet(torch.nn.Module):
    uses_cards = True

    def __init__(self, rows) -> None:
        super().__init__()
        # dummy 参数：让 loss 保留计算图（真实模型由参数提供 requires_grad）
        self.dummy = torch.nn.Parameter(torch.zeros(()))
        self.register_buffer(
            "_rows", torch.as_tensor(np.asarray(rows, dtype=np.float32)))

    def forward(self, features, cards=None):  # 与 tiny 一致：不吃 mask
        b = int(features.shape[0])
        return self._rows[:b] + self.dummy, None, None


def _mask(allowed, n=1):
    m = np.zeros((n, N_ACTIONS), dtype=bool)
    for a in allowed:
        m[:, int(a)] = True
    return m


def _batch(rows, actions, mask=None) -> UpgradeSamples:
    rows = np.atleast_2d(np.asarray(rows, dtype=np.float32))
    n = rows.shape[0]
    actions = np.asarray(actions, dtype=np.int64).reshape(-1)
    assert actions.size == n
    if mask is None:
        mask = np.ones((n, N_ACTIONS), dtype=bool)
    return UpgradeSamples(
        features=np.zeros((n, OBS_FLOATS), dtype=np.float32),
        cards=np.zeros((n, OBS_CARDS), dtype=np.int64),
        action_index=actions,
        action_mask=np.asarray(mask, dtype=bool),
        tier=np.zeros(n, dtype=np.int16),
        turn=np.zeros(n, dtype=np.int16),
        mmr=np.zeros(n, dtype=np.int32),
        tier_known=np.zeros(n, dtype=bool),
        turn_known=np.zeros(n, dtype=bool),
    )


def _logp(chosen_logit, other_logit):
    """mask 只有两个候选时概率归一化后的 log p。"""
    return float(chosen_logit) - float(np.logaddexp(chosen_logit, other_logit))


# ── 1. 手算对照 ───────────────────────────────────────────────────────────
def test_dpo_pair_loss_hand_calc():
    beta = 0.1
    logits = np.zeros(N_ACTIONS, dtype=np.float32)
    logits[UPGRADE_ACTION] = 1.0
    logits[10] = 2.0
    model = _FixedNet([logits])
    batch = _batch([logits], [UPGRADE_ACTION], _mask([UPGRADE_ACTION, 10]))
    loss, rate = dpo_pair_loss(model, batch, beta=beta)
    # chosen 的 logp - rejected 的 logp = 1 - 2 = -1 -> loss = -logsigmoid(-beta)
    expected = -math.log(1.0 / (1.0 + math.exp(-(-beta))))
    expected = math.log1p(math.exp(beta))  # 等价写法，便于核对
    assert float(loss) == pytest.approx(expected, rel=1e-5, abs=1e-6)
    assert rate == pytest.approx(1.0)
    assert torch.is_tensor(loss) and loss.requires_grad
    loss.backward()
    assert model.dummy.grad is not None


# ── 2. chosen == rejected 跳过 ────────────────────────────────────────────
def test_dpo_pair_loss_skips_when_argmax_is_chosen():
    beta = 0.2
    skip_row = np.zeros(N_ACTIONS, dtype=np.float32)
    skip_row[UPGRADE_ACTION] = 5.0          # argmax == chosen -> 跳过
    pair_row = np.zeros(N_ACTIONS, dtype=np.float32)
    pair_row[UPGRADE_ACTION] = 1.0
    pair_row[10] = 2.0
    rows = np.stack([skip_row, pair_row])
    model = _FixedNet(rows)
    mask = _mask([UPGRADE_ACTION, 10], n=2)
    batch = _batch(rows, [UPGRADE_ACTION, UPGRADE_ACTION], mask)
    loss, rate = dpo_pair_loss(model, batch, beta=beta)
    # 接受率 = 1/2；损失只来自第二条（=-logsigmoid(-beta)）
    assert rate == pytest.approx(0.5)
    assert float(loss) == pytest.approx(math.log1p(math.exp(beta)), rel=1e-5,
                                        abs=1e-6)


def test_dpo_pair_loss_all_skipped_returns_zero():
    row = np.zeros(N_ACTIONS, dtype=np.float32)
    row[UPGRADE_ACTION] = 3.0
    model = _FixedNet([row, row])
    batch = _batch([row, row], [UPGRADE_ACTION, UPGRADE_ACTION])
    loss, rate = dpo_pair_loss(model, batch, beta=0.1)
    assert float(loss) == 0.0
    assert rate == 0.0


# ── 3. mask 处理 ─────────────────────────────────────────────────────────
def test_dpo_pair_loss_masks_illegal_actions():
    beta = 0.1
    logits = np.zeros(N_ACTIONS, dtype=np.float32)
    logits[UPGRADE_ACTION] = 1.0
    logits[10] = 2.0
    logits[20] = 99.0                       # 非法（mask 外）：绝不能被选为 rejected
    model = _FixedNet([logits])
    mask = _mask([UPGRADE_ACTION, 10])
    batch = _batch([logits], [UPGRADE_ACTION], mask)
    loss, rate = dpo_pair_loss(model, batch, beta=beta)
    assert float(loss) == pytest.approx(math.log1p(math.exp(beta)), rel=1e-5)
    assert rate == pytest.approx(1.0)

    logp = masked_policy_logprobs(model, batch, chunk=8)
    assert logp.shape == (1, N_ACTIONS)
    assert logp[0, UPGRADE_ACTION] == pytest.approx(_logp(1.0, 2.0), abs=1e-5)
    assert logp[0, 20] < -1e8                # 非法位概率 ≈ 0
    assert int(np.argmax(logp[0])) == 10


def test_dpo_pair_loss_rejects_chosen_outside_mask():
    row = np.zeros(N_ACTIONS, dtype=np.float32)
    model = _FixedNet([row])
    batch = _batch([row], [UPGRADE_ACTION], _mask([10]))  # chosen=3 不在 mask 内
    with pytest.raises(ValueError):
        dpo_pair_loss(model, batch, beta=0.1)


# ── 4. 空样本 ────────────────────────────────────────────────────────────
def test_dpo_pair_loss_empty_batch_returns_zero():
    empty = UpgradeSamples(
        features=np.zeros((0, OBS_FLOATS), dtype=np.float32),
        cards=np.zeros((0, OBS_CARDS), dtype=np.int64),
        action_index=np.zeros(0, dtype=np.int64),
        action_mask=np.zeros((0, N_ACTIONS), dtype=bool),
        tier=np.zeros(0, dtype=np.int16), turn=np.zeros(0, dtype=np.int16),
        mmr=np.zeros(0, dtype=np.int32), tier_known=np.zeros(0, dtype=bool),
        turn_known=np.zeros(0, dtype=bool),
    )
    loss, rate = dpo_pair_loss(_FixedNet(np.zeros((1, N_ACTIONS))), empty, beta=0.1)
    assert float(loss) == 0.0 and rate == 0.0


# ── 5. beta 生效 ─────────────────────────────────────────────────────────
def test_dpo_pair_loss_beta_controls_margin():
    row = np.zeros(N_ACTIONS, dtype=np.float32)
    row[UPGRADE_ACTION] = 1.0
    row[10] = 2.0
    model = _FixedNet([row])
    mask = _mask([UPGRADE_ACTION, 10])
    batch = _batch([row], [UPGRADE_ACTION], mask)
    losses = {}
    for beta in (0.1, 0.5, 1.0):
        loss, _ = dpo_pair_loss(model, batch, beta=beta)
        losses[beta] = float(loss)
        assert losses[beta] == pytest.approx(math.log1p(math.exp(beta)),
                                             rel=1e-5, abs=1e-6)
    assert losses[0.1] < losses[0.5] < losses[1.0]
    with pytest.raises(ValueError):
        dpo_pair_loss(model, batch, beta=0.0)
    with pytest.raises(ValueError):
        dpo_pair_loss(model, batch, beta=-0.1)


# ── 6. 样本加载 ─────────────────────────────────────────────────────────
def _row(**kw):
    base = {"game_id": "g", "turn": 9, "mmr": "7000", "action_type": "upgrade",
            "action_index": UPGRADE_ACTION, "gold": 5, "tier": 4, "health": 30,
            "armor": 0, "hero": None, "board_cards": [], "hand_cards": [],
            "shop_cards": []}
    base.update(kw)
    return base


def test_load_upgrade_samples_filters_and_labels(tmp_path):
    path = tmp_path / "samples.jsonl.gz"
    rows = [
        _row(turn=9, tier=4),                         # 保留
        _row(action_type="sell", action_index=16),    # 非 upgrade：丢
        _row(action_index=None),                      # 不可映射：丢
        _row(mmr="5000"),                             # MMR 不够：丢
        _row(turn=12, tier=3),                        # 保留
    ]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    batch = load_upgrade_samples(str(path), mmr_min=6000)
    assert len(batch) == 2
    # 兼容任务约定的三元组解包
    features, cards, action_index = batch
    assert features.shape == (2, OBS_FLOATS) and features.dtype == np.float32
    assert cards.shape == (2, OBS_CARDS)
    assert np.array_equal(action_index, [UPGRADE_ACTION, UPGRADE_ACTION])
    assert np.array_equal(batch.turn, [9, 12])
    assert np.array_equal(batch.tier, [4, 3])
    assert bool(batch.action_mask[0, UPGRADE_ACTION])
    # limit 是保留条数上限
    assert len(load_upgrade_samples(str(path), mmr_min=6000, limit=1)) == 1


def test_load_upgrade_samples_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("\n")
    batch = load_upgrade_samples(str(path), mmr_min=6000)
    assert len(batch) == 0
