"""复利辅助 BC 的纯合成回归测试；不采集对局、不运行训练实验。"""
import copy
import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip('torch')
from hsbg.az.train import ppo
from hsbg.az.train.common import OBS_FLOATS
from hsbg.env.action_space_std import A_BUY, A_CHOOSE, A_UPGRADE
from hsbg.env.obs_std import (SLICE_CARD_BOARD, SLICE_CARD_HAND,
                              SLICE_CARD_SHOP, SLICE_CARD_CHOICES)
from scripts.train_entity_sync import _attach_replication_bc_labels
from tests.test_az_ppo import _batch_from_model
from hsbg.az.train.model import build_net


@pytest.fixture
def labels(monkeypatch):
    """与真实 PPOBatch 同构的最小 batch。

    ``train_entity_sync._attach_replication_bc_labels`` 无条件读取
    ``batch.features``（tier/gold/price 三个 global 字段）与 ``batch.turns``
    （``scripts/train_entity_sync.py:242-243``；真实批次来自 ``PPOBatch`` 两者都有），
    因此 fixture 必须补齐这两列，否则测试与实现漂移（门禁红）。
    """
    monkeypatch.setattr(ppo, '_rep_card_flags', lambda: {
        10: (0, 3, 1), 11: (0, 6, 2), 12: (0, 6, 1), 13: (1, 6, 0)})
    return SimpleNamespace(cards=np.zeros((1, 124), dtype=np.int16),
                           masks=np.zeros((1, 245), dtype=bool),
                           # 全局特征：tier(10)=tier/6、gold(7)=gold/10、price(11)=price/10
                           features=np.zeros((1, OBS_FLOATS), dtype=np.float32),
                           turns=np.zeros(1, dtype=np.int32))


def test_discover_only_legal_targets(labels):
    labels.cards[0, SLICE_CARD_CHOICES.start:SLICE_CARD_CHOICES.start+3] = [11, 12, 99]
    labels.masks[0, A_CHOOSE:A_CHOOSE+3] = [True, False, True]
    _attach_replication_bc_labels(labels)
    assert labels.discover_bc_idx[0, 0] == A_CHOOSE
    assert labels.discover_bc_w.sum() == 1
    assert (labels.discover_bc_idx[labels.discover_bc_w == 0] == -1).all()


def test_discover_value_weighting(labels):
    labels.cards[0, SLICE_CARD_CHOICES.start:SLICE_CARD_CHOICES.start+2] = [11, 12]
    labels.masks[0, A_CHOOSE:A_CHOOSE+2] = True
    _attach_replication_bc_labels(labels)
    assert labels.discover_bc_w[0, :2] == pytest.approx([0.2, 0.8])


@pytest.mark.parametrize('count, expected', [(1, 1.), (2, 2.)])
def test_buy_pair_triple_weight(labels, count, expected):
    labels.cards[0, SLICE_CARD_BOARD.start:SLICE_CARD_BOARD.start+count] = 11
    labels.cards[0, SLICE_CARD_SHOP.start] = 11
    labels.masks[0, A_BUY] = True
    _attach_replication_bc_labels(labels)
    assert labels.triple_bc_action[0] == A_BUY
    assert labels.triple_bc_w[0] == expected


def test_illegal_buy_and_golden_excluded(labels):
    labels.cards[0, SLICE_CARD_BOARD.start] = 14
    labels.cards[0, SLICE_CARD_SHOP.start:SLICE_CARD_SHOP.start+2] = [14, 11]
    labels.cards[0, SLICE_CARD_HAND.start] = 11
    labels.masks[0, A_BUY] = True
    _attach_replication_bc_labels(labels)
    assert labels.triple_bc_action[0] == -1


def test_upgrade_curve_labels_from_features(labels):
    """``want_upgrade=True``：升级曲线标签确实读 features(tier/gold/price) 与 turns。"""
    labels.turns[0] = 2                       # 默认曲线 {2,5,7,9}
    labels.features[0, 10] = 0.0 / 6.0        # tier=0 < 曲线目标 2
    labels.features[0, 7] = 5.0 / 10.0        # gold=5
    labels.features[0, 11] = 3.0 / 10.0       # price=3 ⇒ 金币够
    labels.masks[0, A_UPGRADE] = True
    stat = _attach_replication_bc_labels(labels, want_upgrade=True)
    assert stat['upgrade_states'] == 1
    assert labels.upgrade_bc_action[0] == A_UPGRADE
    assert labels.upgrade_bc_w[0] == 1.0

    # 非曲线回合（t=3）：即使条件齐也不标
    off_curve = copy.deepcopy(labels)
    off_curve.turns[0] = 3
    assert _attach_replication_bc_labels(
        off_curve, want_upgrade=True)['upgrade_states'] == 0
    assert off_curve.upgrade_bc_action[0] == -1

    # tier 已够（6 >= 目标 2）：不标
    tier_met = copy.deepcopy(labels)
    tier_met.features[0, 10] = 6.0 / 6.0
    assert _attach_replication_bc_labels(
        tier_met, want_upgrade=True)['upgrade_states'] == 0


@pytest.mark.parametrize('coef,bc,pl,expected', [
    (1e-4, 5., 1e-4, 5e-5), (1e-5, .1, 1., 1.5e-5),
    (1e-6, 9., -1e-9, 1e-6), (1e-3, .1, 1., 1e-3),
    (0., 5., 1e-4, 0.)])
def test_guard_extremes(coef, bc, pl, expected):
    new, r = ppo.replication_bc_guard(coef, bc, pl)
    assert new == pytest.approx(expected)
    assert np.isfinite(r)


@pytest.mark.parametrize('normalize', [False, True])
def test_ce_matches_hand_and_masks(normalize):
    logits = torch.tensor([[0., np.log(3), 99.]], requires_grad=True)
    mask = torch.tensor([[True, True, False]])
    logp = ppo.masked_log_softmax_torch(logits, mask)
    ce, n = ppo.replication_bc_ce(logp, mask, torch.tensor([[0, 1, 2, -1, 999]]),
                                torch.tensor([[1., 3., 100., 9., 5.]]), torch.ones(1),
                                normalize=normalize)
    expected = -(np.log(.25)+3*np.log(.75))/4
    if normalize:
        expected /= np.log(2)
    assert n == 1
    assert ce.item() == pytest.approx(expected)
    ce.backward()
    assert logits.grad[0, 2] == 0


def test_forced_and_row_weight():
    logp = torch.log(torch.tensor([[.2, .8], [.4, .6], [.5, .5]]))
    ce, n = ppo.replication_bc_ce(logp, torch.ones(3, 2, dtype=torch.bool),
                                torch.zeros(3, 1, dtype=torch.long),
                                torch.tensor([[2.], [1.], [9.]]),
                                torch.tensor([1., 1., 0.]), row_weight=True)
    assert n == 2
    assert ce.item() == pytest.approx(-(2*np.log(.2)+np.log(.4))/3)


def _sha(model):
    return hashlib.sha256(b''.join(p.detach().numpy().tobytes()
                                  for p in model.parameters())).hexdigest()


def test_zero_coef_two_updates_bitwise():
    torch.manual_seed(41)
    model = build_net(16)
    batch = _batch_from_model(model, n_games=1, decisions_per_seat=2)
    hashes = []
    for guard, with_labels in [(0., False), (.3, True)]:
        m = copy.deepcopy(model)
        b = copy.deepcopy(batch)
        if with_labels:
            b.discover_bc_idx = np.zeros((len(b.actions), 1), dtype=np.int64)
            b.discover_bc_w = np.ones_like(b.discover_bc_idx, dtype=np.float32)
            b.triple_bc_action = np.zeros(len(b.actions), dtype=np.int64)
            b.triple_bc_w = np.ones(len(b.actions), dtype=np.float32)
        cfg = ppo.PPOConfig(epochs=2, minibatch=8, seed=41, bc_guard_ratio=guard,
                            discover_bc_coef=0., triple_bc_coef=0., kl_early_stop=False)
        opt = torch.optim.Adam(m.parameters(), lr=cfg.lr)
        run = []
        for _ in range(2):
            ppo.train_ppo(m, b, cfg, optimizer=opt)
            run.append(_sha(m))
        hashes.append(run)
    assert hashes[0] == hashes[1]


def test_epoch_stats_and_guard_changes():
    torch.manual_seed(42)
    m = build_net(16)
    batch = _batch_from_model(m, n_games=1, decisions_per_seat=2)
    targets = np.argmax(batch.masks, axis=1)
    batch.discover_bc_idx = targets[:, None]
    batch.discover_bc_w = np.ones((len(targets), 1), dtype=np.float32)
    batch.triple_bc_action = targets
    batch.triple_bc_w = np.ones(len(targets), dtype=np.float32)
    cfg = ppo.PPOConfig(epochs=2, minibatch=8, seed=42, bc_guard_ratio=.3,
                        discover_bc_coef=1e-3, triple_bc_coef=1e-3, kl_early_stop=False)
    stats = ppo.train_ppo(m, batch, cfg)
    for rec in [stats, *stats['epochs']]:
        for key in ('bc_scale', 'r', 'policy_loss', 'discover_bc_loss', 'triple_bc_loss',
                    'discover_bc_r', 'triple_bc_r'):
            assert key in rec
    assert stats['epochs'][1]['discover_bc_scale'] < 1.
