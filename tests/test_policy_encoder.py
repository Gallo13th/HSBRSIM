"""策略观测编码器测试：词表 / 实体序列 / 候选动作 / collate 一致性。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.env.spec import (
    CANDIDATE_MAX,
    CARD_TYPE_MINION,
    NUM_ACTION_KINDS,
    PHASE_CHOICE,
    ZONE_BOARD,
    ZONE_CHOICE,
    ZONE_HAND,
    ZONE_TAVERN,
    CandidateAction,
    EntityToken,
    Observation,
    PendingChoice,
)
from hsbg.policy.encoder import (
    CAND_NUM_DIM,
    ENCODER_DIMS,
    ENCODED_KEYS,
    ENTITY_LAYOUT,
    ENTITY_NUM_DIM,
    GLOBAL_DIM,
    NUM_ENTITIES,
    PAD_CARD_INDEX,
    UNK_CARD_INDEX,
    ZONE_OFFSET,
    CardVocab,
    EncoderDims,
    ObservationEncoder,
    collect_card_ids,
    entity_index,
    stack_encoded,
    to_torch,
)
from hsbg.policy.synthetic import FAKE_CARD_IDS, random_observation


@pytest.fixture(scope="module")
def vocab() -> CardVocab:
    return CardVocab(FAKE_CARD_IDS)


@pytest.fixture(scope="module")
def encoder(vocab: CardVocab) -> ObservationEncoder:
    return ObservationEncoder(vocab)


# ══════════════════════════════════════════════════════════════════════
# 词表
# ══════════════════════════════════════════════════════════════════════


def test_vocab_special_tokens_and_unknown(vocab: CardVocab) -> None:
    assert vocab.size == len(FAKE_CARD_IDS) + 2
    assert vocab.index("<PAD>") == PAD_CARD_INDEX == 0
    assert vocab.index("<UNK>") == UNK_CARD_INDEX == 1
    # 未知卡 / 空 id 都映射到安全下标，不抛异常
    assert vocab.index("NOT_A_REAL_CARD_XYZ") == UNK_CARD_INDEX
    assert vocab.index("") == PAD_CARD_INDEX
    assert vocab.index(FAKE_CARD_IDS[0]) == 2


def test_vocab_from_data_dir() -> None:
    vocab = CardVocab.from_data_dir()
    # data/ 存在时应能收集到数千张卡
    assert vocab.size > 1000
    assert vocab.index("BG19_010") > UNK_CARD_INDEX
    assert len(vocab.ids) == vocab.size


def test_vocab_dynamic_from_observations() -> None:
    obs = random_observation(np.random.default_rng(0), card_ids=FAKE_CARD_IDS)
    ids = collect_card_ids(obs)
    assert ids  # 随机观测至少有一些卡
    vocab = CardVocab.from_observations([obs])
    for cid in ids:
        assert cid in vocab
        assert vocab.index(cid) > UNK_CARD_INDEX


def test_vocab_save_load_roundtrip(tmp_path) -> None:
    vocab = CardVocab(FAKE_CARD_IDS[:10])
    path = vocab.save(tmp_path / "vocab.json")
    loaded = CardVocab.load(path)
    assert loaded == vocab
    assert loaded.index(FAKE_CARD_IDS[3]) == vocab.index(FAKE_CARD_IDS[3])
    assert loaded.index("unknown-id") == UNK_CARD_INDEX


# ══════════════════════════════════════════════════════════════════════
# 实体序列布局
# ══════════════════════════════════════════════════════════════════════


def test_entity_layout_indices() -> None:
    assert NUM_ENTITIES == sum(n for _, n in ENTITY_LAYOUT)
    assert ENCODER_DIMS.num_entities == NUM_ENTITIES
    # 各区偏移单调递增且不重叠
    offsets = [ZONE_OFFSET[z] for z, _ in ENTITY_LAYOUT]
    assert offsets == sorted(offsets)
    # 正常引用
    assert entity_index(ZONE_BOARD, 0) == 0
    assert entity_index(ZONE_HAND, 0) == ZONE_OFFSET[ZONE_HAND]
    # 越界安全
    assert entity_index(ZONE_BOARD, 999) == -1
    assert entity_index(ZONE_BOARD, -1) == -1
    assert entity_index("no_such_zone", 0) == -1
    assert entity_index(ZONE_TAVERN, 0) >= 0
    # 全局下标互不重复
    all_idx = {entity_index(z, s) for z, n in ENTITY_LAYOUT for s in range(n)}
    assert len(all_idx) == NUM_ENTITIES
    assert -1 not in all_idx


# ══════════════════════════════════════════════════════════════════════
# 编码
# ══════════════════════════════════════════════════════════════════════


def test_encode_shapes_and_masks(encoder: ObservationEncoder) -> None:
    rng = np.random.default_rng(1)
    obs = random_observation(rng, card_ids=FAKE_CARD_IDS)
    enc = encoder.encode_obs(obs)
    assert set(enc.keys()) == set(ENCODED_KEYS)
    assert enc["entity_card"].shape == (NUM_ENTITIES,)
    assert enc["entity_num"].shape == (NUM_ENTITIES, ENTITY_NUM_DIM)
    assert enc["entity_mask"].shape == (NUM_ENTITIES,)
    assert enc["global"].shape == (GLOBAL_DIM,)
    assert enc["cand_num"].shape == (CANDIDATE_MAX, CAND_NUM_DIM)
    assert enc["cand_mask"].shape == (CANDIDATE_MAX,)
    # mask 数量与观测实体数一致（board+hand+tavern+trinkets+quest+opponent+choice）
    expected = (
        len(obs.board) + len(obs.hand) + len(obs.tavern) + len(obs.trinkets)
        + (1 if obs.quest is not None else 0)
        + len(obs.opponent_board)
        + (len(obs.pending_choice.options) if obs.pending_choice is not None else 0)
    )
    assert int(enc["entity_mask"].sum()) == expected
    # 所有数组有限且 card 下标合法
    for key, arr in enc.items():
        assert np.isfinite(arr).all(), key
    assert (enc["entity_card"] >= 0).all()
    assert (enc["entity_card"] < len(encoder.vocab)).all()
    assert (enc["entity_zone"] >= 0).all()
    assert (enc["entity_zone"] < ENCODER_DIMS.num_zones).all()
    assert (enc["entity_pos"] >= 0).all()
    assert (enc["entity_pos"] < encoder.dims.num_entities).all()
    assert (enc["cand_kind"] >= 0).all()
    assert (enc["cand_kind"] < NUM_ACTION_KINDS).all()


def test_padding_entities_are_zero(encoder: ObservationEncoder) -> None:
    obs = Observation(turn=1, phase="recruit", board=(), hand=(), tavern=(), candidates=())
    obs.candidates = (CandidateAction(kind="end_turn"),)
    enc = encoder.encode_obs(obs)
    assert int(enc["entity_mask"].sum()) == 0
    assert np.all(enc["entity_card"] == 0)
    assert np.all(enc["entity_num"] == 0.0)


def test_candidate_mask_variable_and_truncation(encoder: ObservationEncoder) -> None:
    rng = np.random.default_rng(2)
    lengths = set()
    for _ in range(20):
        obs = random_observation(rng, card_ids=FAKE_CARD_IDS)
        enc = encoder.encode_obs(obs)
        n_valid = int(enc["cand_mask"].sum())
        assert n_valid == min(len(obs.candidates), CANDIDATE_MAX)
        lengths.add(n_valid)
        # 超过 CANDIDATE_MAX 时只保留前 CANDIDATE_MAX 个
        if len(obs.candidates) > CANDIDATE_MAX:
            assert n_valid == CANDIDATE_MAX
    assert len(lengths) > 3  # 候选项数量确实是变长的


def test_candidate_slots_out_of_range_are_safe(encoder: ObservationEncoder) -> None:
    """候选引用不存在的槽位时不得崩溃，且 has_src/has_tgt 置 0。"""
    obs = Observation(turn=2, phase="recruit")
    obs.board = (EntityToken(card_id=FAKE_CARD_IDS[0], card_type=CARD_TYPE_MINION,
                             zone=ZONE_BOARD, slot=0, atk=3, health=4, tier=2),)
    obs.candidates = (
        CandidateAction(kind="buy", src_zone=ZONE_TAVERN, src_slot=99),
        CandidateAction(kind="sell", src_zone=ZONE_BOARD, src_slot=0),
        CandidateAction(kind="play_minion", src_zone=ZONE_HAND, src_slot=-5,
                        tgt_zone=ZONE_BOARD, tgt_slot=77),
    )
    enc = encoder.encode_obs(obs)
    from hsbg.policy.encoder import CAND_FEATURE_OFFSET

    has_src = enc["cand_num"][:3, CAND_FEATURE_OFFSET["has_src"]]
    has_tgt = enc["cand_num"][:3, CAND_FEATURE_OFFSET["has_tgt"]]
    assert has_src.tolist() == [0.0, 1.0, 0.0]
    assert has_tgt.tolist() == [0.0, 0.0, 0.0]
    assert enc["cand_src"][1] == entity_index(ZONE_BOARD, 0)
    # 越界引用统一落到 0 号 padding 位，不会被模型当成真实实体
    assert enc["cand_src"][0] == 0


def test_choose_candidate_points_to_choice_entity(encoder: ObservationEncoder) -> None:
    options = tuple(
        EntityToken(card_id=f"FAKE_MINION_{i:03d}", card_type=CARD_TYPE_MINION,
                    zone=ZONE_CHOICE, slot=i, atk=i, health=i + 1, tier=2)
        for i in range(3)
    )
    obs = Observation(
        turn=5,
        phase=PHASE_CHOICE,
        pending_choice=PendingChoice(kind="triple", options=options, for_agent=True),
        candidates=(CandidateAction(kind="choose", option=2),),
    )
    enc = encoder.encode_obs(obs)
    from hsbg.policy.encoder import CAND_FEATURE_OFFSET

    assert enc["cand_src"][0] == entity_index(ZONE_CHOICE, 2)
    assert enc["cand_num"][0, CAND_FEATURE_OFFSET["has_src"]] == 1.0
    # choice 区实体确实被编码进实体序列
    assert enc["entity_mask"][entity_index(ZONE_CHOICE, 2)] == 1.0
    assert int(enc["entity_mask"].sum()) == 3


def test_global_features_reflect_hero_state(encoder: ObservationEncoder) -> None:
    from hsbg.env.spec import HeroToken

    obs = random_observation(np.random.default_rng(3), card_ids=FAKE_CARD_IDS)
    obs.hero = HeroToken(
        hero_id="FAKE_HERO_000", health=12, armor=3, tier=4, gold=9,
        upgrade_cost=5, power_cost=2, power_usable=True,
    )
    obs.turn = 7
    obs.rank = 3
    enc = encoder.encode_obs(obs)
    from hsbg.policy.encoder import GLOBAL_FEATURE_INDEX

    g = enc["global"]
    assert g[GLOBAL_FEATURE_INDEX["turn"]] == pytest.approx(7 / 15)
    assert g[GLOBAL_FEATURE_INDEX["gold"]] == pytest.approx(9 / 12)
    assert g[GLOBAL_FEATURE_INDEX["tier"]] == pytest.approx(4 / 6)
    assert g[GLOBAL_FEATURE_INDEX["power_usable"]] == 1.0
    assert g[GLOBAL_FEATURE_INDEX["rank"]] == pytest.approx(3 / 8)


# ══════════════════════════════════════════════════════════════════════
# collate
# ══════════════════════════════════════════════════════════════════════


def test_collate_matches_single_encode(encoder: ObservationEncoder) -> None:
    torch = pytest.importorskip("torch")
    rng = np.random.default_rng(4)
    obs_list = [random_observation(rng, card_ids=FAKE_CARD_IDS) for _ in range(4)]
    batch = encoder.collate(obs_list)
    assert set(batch.keys()) == set(ENCODED_KEYS)
    for key in ENCODED_KEYS:
        assert isinstance(batch[key], torch.Tensor)
        assert batch[key].shape[0] == len(obs_list)
    single = encoder.encode_obs(obs_list[0])
    for key in ENCODED_KEYS:
        assert torch.allclose(
            batch[key][0].float(),
            torch.as_tensor(single[key]).float(),
        )
    # dtype 约定：整数 key int64，其余 float32
    for key in ("entity_card", "entity_zone", "entity_pos", "cand_kind", "cand_src", "cand_tgt"):
        assert batch[key].dtype == torch.int64
    for key in ("entity_num", "entity_mask", "global", "cand_num", "cand_mask"):
        assert batch[key].dtype == torch.float32


def test_collate_is_deterministic(encoder: ObservationEncoder) -> None:
    rng = np.random.default_rng(5)
    obs_list = [random_observation(rng, card_ids=FAKE_CARD_IDS) for _ in range(3)]
    b1 = encoder.collate(obs_list)
    b2 = encoder.collate(obs_list)
    for key in ENCODED_KEYS:
        assert np.array_equal(b1[key].numpy(), b2[key].numpy())


def test_stack_encoded_and_to_torch_roundtrip(encoder: ObservationEncoder) -> None:
    torch = pytest.importorskip("torch")
    rng = np.random.default_rng(6)
    samples = [encoder.encode_obs(random_observation(rng, card_ids=FAKE_CARD_IDS)) for _ in range(2)]
    stacked = stack_encoded(samples)
    assert stacked["global"].shape[0] == 2
    t = to_torch(stacked)
    assert torch.is_tensor(t["global"])
    with pytest.raises(ValueError):
        stack_encoded([])


def test_encoder_meta_roundtrip(encoder: ObservationEncoder) -> None:
    meta = encoder.to_meta()
    restored = ObservationEncoder.from_meta(meta)
    assert restored.vocab == encoder.vocab
    assert restored.dims == encoder.dims
    assert restored.dims.as_spec_obs_dims().candidate_max == CANDIDATE_MAX


def test_encoder_dims_defaults() -> None:
    dims = EncoderDims()
    assert dims.num_entities == NUM_ENTITIES
    assert dims.entity_num_dim == ENTITY_NUM_DIM
    assert dims.global_dim == GLOBAL_DIM
    assert dims.cand_num_dim == CAND_NUM_DIM
    assert dims.candidate_max == CANDIDATE_MAX
    assert EncoderDims.from_dict(dims.as_dict()) == dims
