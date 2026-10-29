"""分层 BC（动作类型 + 卡牌身份）单测。

覆盖：
1. 245 动作 -> 动作段 / 9 类的映射：每个动作唯一归属、play_minion/play_spell
   按样本观测到的**手牌卡种**细分（静态无法区分）；
2. 类型级 CE：245 logits 的 log-sum-exp 聚合与手算一致、数值稳定、空类型不 NaN；
3. 卡牌身份：``card_id`` -> 卡表 0-based 标签、映射失败/非 buy-play 跳过、
   ``bc_card_ce_loss`` 只在有效样本上平均；
4. 两层权重：``loss = w_type*CE_type + w_card*CE_card`` 线性生效；
5. ``bc_coef=0`` 逐位等价：同 seed ``model.pt`` SHA256 相同，且不建 ``card_head``；
6. ramp 边界：``5e-4@0,5e-3@0.5`` 的 0 / 中点 / 终点 / 超界。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.bc_aux import (
    ACTION_TYPE_TABLE,
    BC_ACTION_CLASSES,
    BC_CARD_CLASS_IDS,
    BC_STATIC_TYPE_IDS,
    BC_TYPE_CLASSES,
    N_BC_TYPES,
    STD_ACTION_SEGMENT,
    bc_card_ce_loss,
    bc_ce_loss,
    bc_hier_loss,
    bc_obs_batch,
    bc_type_ids,
    bc_type_logits,
    load_bc_card_table,
    load_bc_samples,
    parse_bc_coef_ramp,
)
from hsbg.env import action_space_std as ACT
from hsbg.env import obs_std as O


# ── fixtures：小卡表 + 小 JSONL ───────────────────────────────────────────
def _write_cards(path):
    """4 张卡：index 1=随从, 2=法术, 3=金色随从, 4=英雄。"""
    cards = [
        {"id": "TEST_MINION", "kind": "minion", "tier": 1, "atk": 2, "hp": 3,
         "cost": 3, "races": ["BEAST"], "keywords": ["TAUNT"]},
        {"id": "TEST_SPELL", "kind": "spell", "tier": 2, "atk": 0, "hp": 0,
         "cost": 2, "races": [], "keywords": []},
        {"id": "TEST_MINION_G", "kind": "minion", "tier": 2, "atk": 4, "hp": 6,
         "cost": 3, "races": ["BEAST"], "keywords": []},
        {"id": "TEST_HERO", "kind": "hero", "tier": 0, "atk": 0, "hp": 0,
         "cost": 0, "races": [], "keywords": []},
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": {"count": len(cards)}, "cards": cards}, f)
    return path


def _row(**kw):
    base = {
        "game_id": "g", "turn": 5, "mmr": "7000", "action_type": "sell",
        "action_index": 16, "gold": 5, "tier": 2, "health": 30, "armor": 0,
        "hero": "TEST_HERO", "board_cards": ["TEST_MINION"],
        "board_pos": [0], "hand_cards": [], "hand_pos": [],
        "shop_cards": ["TEST_MINION", "TEST_SPELL"], "shop_pos": [0, 7],
        "card_id": "TEST_MINION",
    }
    base.update(kw)
    return base


def _write_jsonl(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


@pytest.fixture()
def bc_data(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    rows = [
        # 0 sell：card_id 有效，但 sell 不属于 buy/play -> card_valid=False
        _row(),
        # 1 buy_minion：card_id 有效 -> card_valid=True（标签 0）
        _row(action_type="buy_minion", action_index=8, mmr=9000,
             card_id="TEST_MINION"),
        # 2 buy_minion：card_id 映射失败 -> card_valid=False
        _row(action_type="buy_minion", action_index=8, mmr=9000,
             card_id="NOT_IN_CARDS"),
        # 3 play_spell：手牌有法术 -> type=play_spell，card_valid=True（标签 1）
        _row(action_type="play_spell", action_index=46, mmr=6200,
             hand_cards=["TEST_SPELL"], hand_pos=[0], board_cards=[],
             board_pos=[], shop_cards=[], shop_pos=[], card_id="TEST_SPELL"),
    ]
    path = _write_jsonl(tmp_path / "bc.jsonl.gz", rows)
    return path, cards


def _torch():
    return pytest.importorskip("torch")


# ══════════════════════════════════════════════════════════════════════════
# 1. 动作段 / 类型映射
# ══════════════════════════════════════════════════════════════════════════
def test_action_segment_table_covers_all_245_uniquely():
    assert len(STD_ACTION_SEGMENT) == N_ACTIONS
    # 与 action_space_std.SEGMENTS 同源（不是硬编码偏移）
    for name, lo, hi, _count, _desc in ACT.SEGMENTS:
        for i in range(lo, min(hi, N_ACTIONS)):
            assert STD_ACTION_SEGMENT[i] == name
    assert len(set(STD_ACTION_SEGMENT)) == 14
    # 每个动作恰好一个段：SEGMENTS 连续覆盖 0..244（action_space_std 自检）
    assert [STD_ACTION_SEGMENT[0], STD_ACTION_SEGMENT[244]] == [
        "end_turn", "move"]
    assert STD_ACTION_SEGMENT[ACT.A_BUY] == "buy"
    assert STD_ACTION_SEGMENT[ACT.A_PLAY] == "play"
    assert STD_ACTION_SEGMENT[ACT.A_PLAY + ACT.N_HAND * ACT.N_POS - 1] == "play"


def test_action_type_table_unique_245():
    """每个动作唯一归属一个类型名；buy 按槽位分 minion/spell；play 保留段名。"""
    assert len(ACTION_TYPE_TABLE) == N_ACTIONS
    # 静态 buy：0..6 minion，7（A_BUY+7=15）spell
    assert set(ACTION_TYPE_TABLE[ACT.A_BUY:ACT.A_BUY + ACT.N_SHOP - 1]) == {
        "buy_minion"}
    assert ACTION_TYPE_TABLE[ACT.A_BUY + ACT.N_SHOP - 1] == "buy_spell"
    assert set(ACTION_TYPE_TABLE[ACT.A_PLAY:
                                 ACT.A_PLAY + ACT.N_HAND * ACT.N_POS]) == {
        "play"}
    # 白名单中的 7 个静态类型名都出现在表里（play 两类由 bc_type_ids 细分为 play 段）
    for name in ("sell", "reroll", "buy_minion", "buy_spell", "upgrade",
                 "hero_power", "end_turn"):
        assert name in ACTION_TYPE_TABLE, name
    # 与 BC_STATIC_TYPE_IDS 自洽：表里对应 9 类名的动作，其静态 id 必须是该类
    for a, name in enumerate(ACTION_TYPE_TABLE):
        if name in BC_ACTION_CLASSES and name not in ("play_minion", "play_spell"):
            assert int(BC_STATIC_TYPE_IDS[a]) == BC_ACTION_CLASSES[name], a
        elif name not in ("play",):
            assert int(BC_STATIC_TYPE_IDS[a]) == -1, a


def test_static_type_ids_cover_9_classes():
    assert BC_TYPE_CLASSES == (
        "sell", "reroll", "buy_minion", "buy_spell", "play_spell",
        "play_minion", "upgrade", "hero_power", "end_turn")
    assert N_BC_TYPES == 9
    # 静态 20 个动作：end_turn(1)+reroll(1)+upgrade(1)+hero(2)+sell(7)+
    # buy_minion(7)+buy_spell(1)
    assert int((BC_STATIC_TYPE_IDS >= 0).sum()) == 20
    # play 段必须全部留空（由 bc_type_ids 按手牌卡种细分）
    assert np.all(BC_STATIC_TYPE_IDS[ACT.A_PLAY:
                                     ACT.A_PLAY + ACT.N_HAND * ACT.N_POS] == -1)
    # 非白名单动作不参与类型聚合
    for a in (ACT.A_FREEZE, ACT.A_DARK_GIFT, ACT.A_CANCEL, ACT.A_ACTIVATE,
              ACT.A_CHOOSE, ACT.A_MAGNETIZE, ACT.A_MOVE):
        assert int(BC_STATIC_TYPE_IDS[a]) == -1
    # 每类都有来源：静态 7 类 + 动态 play 2 类
    static_classes = set(np.unique(
        BC_STATIC_TYPE_IDS[BC_STATIC_TYPE_IDS >= 0]).tolist())
    play_ids = {BC_ACTION_CLASSES["play_spell"], BC_ACTION_CLASSES["play_minion"]}
    assert static_classes == set(range(N_BC_TYPES)) - play_ids
    # buy 段：8..14 = buy_minion，15（酒馆法术槽）= buy_spell
    assert set(np.unique(BC_STATIC_TYPE_IDS[8:15]).tolist()) == {
        BC_ACTION_CLASSES["buy_minion"]}
    assert int(BC_STATIC_TYPE_IDS[15]) == BC_ACTION_CLASSES["buy_spell"]


def test_bc_type_ids_play_split_and_unique_membership(bc_data, tmp_path):
    _path, cards = bc_data
    table = load_bc_card_table(cards)
    minion = table.id_to_index["TEST_MINION"]
    spell = table.id_to_index["TEST_SPELL"]
    hand = np.zeros((1, O.N_HAND), dtype=np.int32)
    present = np.zeros((1, O.N_HAND), dtype=bool)
    hand[0, 0], present[0, 0] = minion, True    # 手牌 0 = 随从
    hand[0, 1], present[0, 1] = spell, True     # 手牌 1 = 法术
    samples = SimpleNamespace(
        card_table=table, hand=hand, hand_present=present,
        action_index=np.array([8], dtype=np.int64),      # buy_minion
        action_class=np.array([BC_ACTION_CLASSES["buy_minion"]], dtype=np.int16),
    )
    ids = bc_type_ids(samples, [0])
    assert ids.shape == (1, N_ACTIONS)
    # 每个动作只有一个 int16 值（数组天然唯一）；值域 = 9 类或 -1
    assert set(np.unique(ids).tolist()) <= set(range(N_BC_TYPES)) | {-1}
    # 随从手牌 0：play 46..53 全部 = play_minion
    base0 = ACT.A_PLAY
    assert np.all(ids[0, base0:base0 + ACT.N_POS]
                  == BC_ACTION_CLASSES["play_minion"])
    # 法术手牌 1：只有 pos=0（54）是 play_spell，pos 1..7 不参与
    base1 = ACT.A_PLAY + ACT.N_POS
    assert int(ids[0, base1]) == BC_ACTION_CLASSES["play_spell"]
    assert np.all(ids[0, base1 + 1:base1 + ACT.N_POS] == -1)
    # 静态映射
    for a, name in ((ACT.A_END, "end_turn"), (ACT.A_REFRESH, "reroll"),
                    (ACT.A_UPGRADE, "upgrade"),
                    (ACT.A_HERO_POWER, "hero_power"),
                    (ACT.A_HERO_POWER + 1, "hero_power"),
                    (ACT.A_SELL, "sell"),
                    (ACT.A_SELL + ACT.N_BOARD - 1, "sell"),
                    (ACT.A_BUY, "buy_minion"),
                    (ACT.A_BUY + ACT.N_SHOP - 1, "buy_spell")):
        assert int(ids[0, a]) == BC_ACTION_CLASSES[name]
    # 非白名单动作不归属任何类型
    for a in (ACT.A_FREEZE, ACT.A_DARK_GIFT, ACT.A_CANCEL, ACT.A_ACTIVATE,
              ACT.A_CHOOSE, ACT.A_MAGNETIZE, ACT.A_MOVE):
        assert int(ids[0, a]) == -1

    # 手牌未知时：真实动作仍被强制归入其 action_type（标签优先）
    unknown = SimpleNamespace(
        card_table=table, hand=np.zeros((1, O.N_HAND), dtype=np.int32),
        hand_present=np.zeros((1, O.N_HAND), dtype=bool),
        action_index=np.array([46], dtype=np.int64),
        action_class=np.array([BC_ACTION_CLASSES["play_spell"]], dtype=np.int16),
    )
    ids2 = bc_type_ids(unknown, [0])
    assert int(ids2[0, 46]) == BC_ACTION_CLASSES["play_spell"]
    assert int(ids2[0, 47]) == -1


# ══════════════════════════════════════════════════════════════════════════
# 2. 类型级 CE：手算 + 数值稳定
# ══════════════════════════════════════════════════════════════════════════
def test_bc_type_logits_logsumexp_matches_manual():
    torch = _torch()
    logits = torch.zeros(1, N_ACTIONS)
    tids = np.full((1, N_ACTIONS), -1, dtype=np.int64)
    sell, buy_minion, end_turn = (BC_ACTION_CLASSES["sell"],
                                  BC_ACTION_CLASSES["buy_minion"],
                                  BC_ACTION_CLASSES["end_turn"])
    tids[0, ACT.A_SELL:ACT.A_SELL + ACT.N_BOARD] = sell       # 7 个
    tids[0, ACT.A_BUY:ACT.A_BUY + ACT.N_SHOP - 1] = buy_minion  # 7 个
    tids[0, ACT.A_END] = end_turn                             # 1 个
    am = np.ones((1, N_ACTIONS), dtype=bool)
    tl = bc_type_logits(logits, tids, am)
    assert tuple(tl.shape) == (1, N_BC_TYPES)
    assert float(tl[0, sell]) == pytest.approx(np.log(7.0), abs=1e-6)
    assert float(tl[0, buy_minion]) == pytest.approx(np.log(7.0), abs=1e-6)
    assert float(tl[0, end_turn]) == pytest.approx(0.0, abs=1e-6)
    # 空类型 = 有限哨兵（不是 -inf / NaN）
    for c in set(range(N_BC_TYPES)) - {sell, buy_minion, end_turn}:
        assert float(tl[0, c]) < -1e20
    # 手算 CE：target=sell -> -log(7/15)
    got = bc_ce_loss(tl, torch.tensor([sell]))
    assert float(got) == pytest.approx(float(np.log(15.0 / 7.0)), abs=1e-6)

    # 动作掩码生效：把 sell 的 6 个候选屏蔽后只剩 1 个 -> log(1)=0
    am2 = am.copy()
    am2[0, ACT.A_SELL + 1:ACT.A_SELL + ACT.N_BOARD] = False
    tl2 = bc_type_logits(logits, tids, am2)
    assert float(tl2[0, sell]) == pytest.approx(0.0, abs=1e-6)

    # 数值稳定：全体 logits=1e4 时 logsumexp 仍有限且约等于 1e4+log(n)
    big = torch.full((1, N_ACTIONS), 1e4)
    tlb = bc_type_logits(big, tids, am)
    assert bool(torch.isfinite(tlb[0, [sell, buy_minion, end_turn]]).all())
    assert float(tlb[0, sell]) == pytest.approx(1e4 + np.log(7.0), abs=1e-2)
    # 空类型填充 -1e30 后 CE 仍有限（target 非空）
    ce_big = bc_ce_loss(tlb, torch.tensor([sell]))
    assert bool(torch.isfinite(ce_big))


# ══════════════════════════════════════════════════════════════════════════
# 3. 卡牌身份标签 / 失败跳过
# ══════════════════════════════════════════════════════════════════════════
def test_card_label_mapping_and_loss_skips_failures(bc_data):
    torch = _torch()
    path, cards = bc_data
    s = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    assert len(s) == 4
    # TEST_MINION 是 cards[0] -> 卡表 index 1 -> label 0
    assert s.card_target.tolist() == [0, 0, -1, 1]
    assert s.card_valid.tolist() == [False, True, False, True]
    b = bc_obs_batch(s)
    assert b.card_target.tolist() == s.card_target.tolist()
    assert b.card_valid.tolist() == s.card_valid.tolist()
    # 每一行的真实动作都归入自己的 action_type 类型
    for r in range(len(s)):
        assert int(b.type_ids[r, int(b.action_index[r])]) == int(b.class_ids[r])

    card_logits = torch.zeros(4, 7)
    target = torch.as_tensor(b.card_target.astype(np.int64))
    valid = torch.as_tensor(b.card_valid.astype(bool))
    loss = bc_card_ce_loss(card_logits, target, mask=valid,
                           weights=torch.ones(4))
    # 只有行 1/3 有效：CE(0) 与 CE(1) 的均值
    manual = (float(torch.nn.functional.cross_entropy(
        card_logits[[1]], torch.tensor([0])))
        + float(torch.nn.functional.cross_entropy(
            card_logits[[3]], torch.tensor([1])))) / 2.0
    assert float(loss) == pytest.approx(manual, abs=1e-6)
    # 全部无效 / target=-1：返回 0 且不报错
    zero = bc_card_ce_loss(card_logits, torch.full((4,), -1, dtype=torch.long),
                           mask=torch.zeros(4, dtype=torch.bool))
    assert float(zero) == 0.0 and bool(torch.isfinite(zero))

    # buy/play 样本集合与文档一致
    assert set(BC_CARD_CLASS_IDS) == {
        BC_ACTION_CLASSES["buy_minion"], BC_ACTION_CLASSES["buy_spell"],
        BC_ACTION_CLASSES["play_minion"], BC_ACTION_CLASSES["play_spell"]}


# ══════════════════════════════════════════════════════════════════════════
# 4. 两层权重
# ══════════════════════════════════════════════════════════════════════════
def test_hier_loss_two_layer_weights_linear():
    torch = _torch()
    tids = np.tile(BC_STATIC_TYPE_IDS.astype(np.int64), (2, 1))
    # 两行目标：sell 与 buy_minion
    target = np.array([BC_ACTION_CLASSES["sell"],
                       BC_ACTION_CLASSES["buy_minion"]], dtype=np.int64)
    logits = torch.zeros(2, N_ACTIONS)
    card_logits = torch.zeros(2, 11)
    card_target = torch.tensor([0, 5])
    card_valid = torch.tensor([True, True])
    weights = torch.tensor([1.0, 1.5])
    am = np.ones((2, N_ACTIONS), dtype=bool)
    counts = np.ones(N_BC_TYPES, dtype=np.int64)

    h = bc_hier_loss(logits, tids, target, action_mask=am,
                     card_logits=card_logits, card_target=card_target,
                     card_valid=card_valid, weights=weights,
                     class_counts=counts, type_weight=1.0, card_weight=0.5)
    assert float(h["loss"]) == pytest.approx(
        float(h["type_loss"]) + 0.5 * float(h["card_loss"]), abs=1e-6)
    # 只留 type
    h_t = bc_hier_loss(logits, tids, target, action_mask=am,
                       card_logits=card_logits, card_target=card_target,
                       card_valid=card_valid, weights=weights,
                       class_counts=counts, type_weight=2.0, card_weight=0.0)
    assert float(h_t["loss"]) == pytest.approx(
        2.0 * float(h_t["type_loss"]), abs=1e-6)
    assert float(h_t["card_loss"]) == 0.0
    # 只留 card
    h_c = bc_hier_loss(logits, tids, target, action_mask=am,
                       card_logits=card_logits, card_target=card_target,
                       card_valid=card_valid, weights=weights,
                       class_counts=counts, type_weight=0.0, card_weight=3.0)
    assert float(h_c["loss"]) == pytest.approx(
        3.0 * float(h_c["card_loss"]), abs=1e-6)
    # 没有 card_head（card_logits=None）时 card 项为 0
    h_none = bc_hier_loss(logits, tids, target, action_mask=am,
                          card_logits=None, card_target=card_target,
                          card_valid=card_valid, weights=weights,
                          class_counts=counts, type_weight=1.0, card_weight=1.0)
    assert float(h_none["card_loss"]) == 0.0
    assert float(h_none["loss"]) == pytest.approx(float(h_none["type_loss"]))


def test_ppo_config_rejects_negative_bc_weights():
    from hsbg.az.train.ppo import PPOConfig
    PPOConfig(bc_type_weight=0.0, bc_card_weight=0.0)
    with pytest.raises(ValueError):
        PPOConfig(bc_type_weight=-1.0)
    with pytest.raises(ValueError):
        PPOConfig(bc_card_weight=-1.0)


# ══════════════════════════════════════════════════════════════════════════
# 5. 模型/card_head/checkpoint
# ══════════════════════════════════════════════════════════════════════════
def test_bc_card_head_build_attach_and_checkpoint_roundtrip(tmp_path):
    torch = _torch()
    from hsbg.az.train.model import (attach_bc_card_head, bc_card_head_dim,
                                     build_net, load_checkpoint,
                                     save_checkpoint)
    torch.manual_seed(0)
    base = build_net(256)
    assert getattr(base, "card_head", None) is None
    n_base = sum(p.numel() for p in base.parameters())

    torch.manual_seed(0)
    with_head = build_net(256, bc_card_head=True, bc_card_dim=37)
    assert with_head.card_head is not None
    assert int(with_head.card_head.out_features) == 37
    assert bc_card_head_dim(with_head) == 256
    assert sum(p.numel() for p in with_head.parameters()) == n_base + 256 * 37 + 37

    x = torch.zeros(3, OBS_FLOATS)
    c = torch.zeros(3, OBS_CARDS, dtype=torch.long)
    policy, card = with_head.forward_bc(x, c)
    assert tuple(policy.shape) == (3, N_ACTIONS)
    assert tuple(card.shape) == (3, 37)

    # attach 幂等
    attached = attach_bc_card_head(base, dim=37)
    assert attached is base
    assert int(base.card_head.out_features) == 37
    assert attach_bc_card_head(base, dim=99) is base
    assert int(base.card_head.out_features) == 37

    # save/load：meta.bc_card_head 与权重都保留
    path = tmp_path / "with_head.pt"
    save_checkpoint(with_head, str(path), meta={"arch": "tiny"})
    loaded, meta = load_checkpoint(str(path))
    assert meta.get("bc_card_head") is True
    assert int(meta.get("bc_card_dim")) == 37
    assert loaded.card_head is not None
    assert int(loaded.card_head.out_features) == 37
    sd_a, sd_b = with_head.state_dict(), loaded.state_dict()
    assert set(sd_a) == set(sd_b)
    for k in sd_a:
        assert torch.equal(sd_a[k], sd_b[k]), k

    # 不建头时 checkpoint 不出现 card_head / meta 为 False
    path2 = tmp_path / "no_head.pt"
    save_checkpoint(build_net(256), str(path2), meta={"arch": "tiny"})
    payload = torch.load(str(path2), map_location="cpu", weights_only=True)
    assert payload["meta"].get("bc_card_head") is False
    assert not any(str(k).startswith("card_head.") for k in payload["state_dict"])


def test_bc_coef_zero_bit_identical_model_pt(tmp_path, bc_data):
    torch = _torch()
    from hsbg.az.train.model import build_net, save_checkpoint
    from hsbg.az.train.ppo import (
        PPOConfig, build_batch_from_records, masked_probs_np, train_ppo,
        value_from_rank_logits_np,
    )

    torch.manual_seed(0)
    m0 = build_net(16)
    torch.manual_seed(0)
    m1 = build_net(16)
    # 两个模型必须同 seed（build_net 内部无随机，但显式对齐更稳）
    sd0, sd1 = m0.state_dict(), m1.state_dict()
    for k in sd0:
        assert torch.equal(sd0[k], sd1[k])

    # 用模型自身分布生成合法 PPO 批次（无需引擎）
    rng = np.random.default_rng(0)
    m0.eval()
    records = []
    for i in range(8):
        features = rng.normal(size=OBS_FLOATS).astype(np.float32)
        cards = np.zeros(OBS_CARDS, dtype=np.int32)
        mask = np.zeros(N_ACTIONS, dtype=bool)
        mask[[0, 1, 8, 16, 46]] = True
        with torch.no_grad():
            out = m0(torch.from_numpy(features.reshape(1, -1)),
                     torch.from_numpy(cards.astype(np.int64).reshape(1, -1)))
        probs = masked_probs_np(out[0].numpy()[0], mask)
        probs = probs / max(float(probs.sum()), 1e-12)
        action = int(rng.choice(N_ACTIONS, p=probs))
        records.append({
            "features": features, "cards": cards, "mask": mask,
            "action": action,
            "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
            "value": float(value_from_rank_logits_np(out[1].numpy()[0])[0]),
            "rank": 1 + (i % 8), "seat": i % 8, "game_id": i // 8,
            "turn": 1,
        })
    batch = build_batch_from_records(records, gamma=1.0, lam=0.95)

    path, cards = bc_data
    pool = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    cfg0 = PPOConfig(epochs=1, minibatch=4, lr=1e-3, seed=0, target_kl=10.0,
                     value_loss="rank", pi_coef=0.0, bc_coef=0.0)
    cfg1 = PPOConfig(epochs=1, minibatch=4, lr=1e-3, seed=0, target_kl=10.0,
                     value_loss="rank", pi_coef=0.0, bc_coef=0.0,
                     bc_samples_path=path, bc_type_weight=1.0,
                     bc_card_weight=0.5)
    stats0 = train_ppo(m0, batch, cfg0, rng=np.random.default_rng(0))
    stats1 = train_ppo(m1, batch, cfg1, bc_pool=pool,
                       rng=np.random.default_rng(0))
    sd0, sd1 = m0.state_dict(), m1.state_dict()
    assert set(sd0) == set(sd1)
    assert not any(str(k).startswith("card_head.") for k in sd0)
    for k in sd0:
        assert torch.equal(sd0[k], sd1[k]), f"权重不一致: {k}"

    a = tmp_path / "run_a" / "model.pt"
    b = tmp_path / "run_b" / "model.pt"
    a.parent.mkdir(parents=True, exist_ok=True)
    b.parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint(m0, str(a), meta={"arch": "tiny", "seed": 0})
    save_checkpoint(m1, str(b), meta={"arch": "tiny", "seed": 0})
    sha_a = hashlib.sha256(a.read_bytes()).hexdigest()
    sha_b = hashlib.sha256(b.read_bytes()).hexdigest()
    assert sha_a == sha_b, f"bc_coef=0 时 model.pt 不一致: {sha_a} != {sha_b}"

    # stats 不出现 bc_* 字段，config 回显也清掉
    for st in (stats0, stats1):
        assert "bc_loss" not in st
        assert "bc_type_loss" not in st
        assert "bc_card_loss" not in st
        for key in ("bc_coef", "bc_coef_ramp", "bc_type_weight", "bc_card_weight"):
            assert key not in st["config"]
    e0 = [{k: v for k, v in r.items() if k != "elapsed_s"}
          for r in stats0["epochs"]]
    e1 = [{k: v for k, v in r.items() if k != "elapsed_s"}
          for r in stats1["epochs"]]
    assert e0 == e1


def test_bc_coef_positive_reports_hier_stats(bc_data):
    torch = _torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import PPOConfig, build_batch_from_records, \
        masked_probs_np, train_ppo, value_from_rank_logits_np

    path, cards = bc_data
    pool = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    torch.manual_seed(0)
    model = build_net(16)
    model.eval()
    rng = np.random.default_rng(0)
    records = []
    for i in range(8):
        features = rng.normal(size=OBS_FLOATS).astype(np.float32)
        cards_arr = np.zeros(OBS_CARDS, dtype=np.int32)
        mask = np.zeros(N_ACTIONS, dtype=bool)
        mask[[0, 1, 8, 16, 46]] = True
        with torch.no_grad():
            out = model(torch.from_numpy(features.reshape(1, -1)),
                        torch.from_numpy(cards_arr.astype(np.int64).reshape(1, -1)))
        probs = masked_probs_np(out[0].numpy()[0], mask)
        probs = probs / max(float(probs.sum()), 1e-12)
        action = int(rng.choice(N_ACTIONS, p=probs))
        records.append({
            "features": features, "cards": cards_arr, "mask": mask,
            "action": action,
            "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
            "value": float(value_from_rank_logits_np(out[1].numpy()[0])[0]),
            "rank": 1 + (i % 8), "seat": i % 8, "game_id": i // 8,
            "turn": 1,
        })
    batch = build_batch_from_records(records, gamma=1.0, lam=0.95)
    cfg = PPOConfig(epochs=1, minibatch=4, lr=1e-4, seed=0, target_kl=10.0,
                    value_loss="rank", pi_coef=0.0, bc_coef=0.01, bc_batch=4,
                    bc_samples_path=path, bc_type_weight=1.0,
                    bc_card_weight=0.5)
    stats = train_ppo(model, batch, cfg, bc_pool=pool,
                      rng=np.random.default_rng(0))
    for key in ("bc_loss", "bc_type_loss", "bc_card_loss", "bc_coef",
                "bc_samples", "bc_type_weight", "bc_card_weight"):
        assert key in stats, key
    assert np.isfinite(stats["bc_type_loss"])
    # 模型没有 card_head -> 卡牌层恒 0（不制造假梯度）
    assert stats["bc_card_loss"] == 0.0
    assert stats["bc_type_weight"] == pytest.approx(1.0)
    assert stats["bc_card_weight"] == pytest.approx(0.5)


# ══════════════════════════════════════════════════════════════════════════
# 6. ramp 边界
# ══════════════════════════════════════════════════════════════════════════
def test_bc_ramp_boundaries():
    from hsbg.az.train.seq_aux import SeqCoefSchedule
    spec = "5e-4@0,5e-3@0.5"
    points = parse_bc_coef_ramp(spec)
    assert points == [(0.0, 5e-4), (0.5, 5e-3)]
    sched = SeqCoefSchedule.from_spec(base_coef=0.0, spec=spec,
                                      total_decisions=1000.0)
    assert sched.enabled
    assert sched.coef(0) == pytest.approx(5e-4)
    # progress=0.25 -> 两控制点中点
    assert sched.coef(250) == pytest.approx((5e-4 + 5e-3) / 2.0)
    assert sched.coef(500) == pytest.approx(5e-3)
    # progress > 1 clamp 到最后一个点
    assert sched.coef(10_000) == pytest.approx(5e-3)
    # total_decisions<=0 -> 进度恒 0（停在第一个点）
    sched0 = SeqCoefSchedule.from_spec(base_coef=0.0, spec=spec,
                                       total_decisions=0.0)
    assert sched0.coef(12345) == pytest.approx(5e-4)
    # 非法 ramp 在解析期失败
    with pytest.raises(ValueError):
        parse_bc_coef_ramp("bad")
    with pytest.raises(ValueError):
        parse_bc_coef_ramp("1e-3@1.5")


# ══════════════════════════════════════════════════════════════════════════
# 7. 真实数据（存在才跑）
# ══════════════════════════════════════════════════════════════════════════
def test_real_bc_pool_hier_fields():
    from hsbg.az.train.bc_aux import DEFAULT_BC_SAMPLES_PATH
    if not os.path.isfile(DEFAULT_BC_SAMPLES_PATH):
        pytest.skip("真实 BC 数据不存在")
    s = load_bc_samples(DEFAULT_BC_SAMPLES_PATH, mmr_min=6000, limit=300)
    assert len(s) == 300
    assert s.card_target.shape == (300,)
    assert s.card_valid.shape == (300,)
    assert np.all(s.card_target >= -1)
    assert np.all(s.card_target < 3984)
    assert np.all(s.card_target[s.card_valid] >= 0)
    # 非 buy/play 类别不参与 card CE（即使 card_id 能映射）
    non_card = ~np.isin(s.action_class, np.asarray(BC_CARD_CLASS_IDS))
    assert not np.any(s.card_valid & non_card)
    assert int(s.card_valid.sum()) > 0
    b = bc_obs_batch(s, indices=np.arange(min(16, len(s))))
    assert b.type_ids.shape == (min(16, len(s)), N_ACTIONS)
    for r in range(len(b)):
        # 真实动作一定归入自己的类型（类型 CE 分母非空）
        assert int(b.type_ids[r, int(b.action_index[r])]) == int(b.class_ids[r])
    # 类型标签都在 [0,9)；play_* 的动态映射不应产生越界值
    assert int(b.type_ids.max()) < N_BC_TYPES
    assert int(b.type_ids.min()) >= -1
