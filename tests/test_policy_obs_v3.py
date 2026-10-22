"""观测 v3（2026-10-22）策略适配测试。

覆盖三件事（对应 task-7）：

1. **13 种动作 kind / MOVE_MINION**：``ACTION_KIND_INDEX`` 追加在末尾、既有
   12 类索引不变；move_minion 候选能正确编码（kind one-hot、position、src），
   含 move 候选的 batch 能 forward / 采样且 masked softmax 有限。
2. **``extra["pending_choice_options"]``**（Dark Gift 的 gift_id / 任务 offer 的
   reward_id）：secondary_id 进入 ``entity_secondary`` 编码张量并被模型消费；
   card_id 仍走 ``entity_card``；缺失/畸形 extra（v2 观测、脏数据）不崩。
3. **旧 checkpoint 兼容性**：观测 v2 时代 ckpt 默认抛
   ``CheckpointCompatibilityError``（带迁移说明）；``allow_legacy=True`` 内存
   迁移与 ``migrate_legacy_checkpoint`` 落盘迁移都能保留旧权重并跑通 v3 前向。
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.env.spec import (
    ACTION_KIND_INDEX,
    CANDIDATE_MAX,
    CARD_TYPE_MINION,
    NUM_ACTION_KINDS,
    PHASE_CHOICE,
    ZONE_BOARD,
    ZONE_CHOICE,
    ActionKind,
    CandidateAction,
    EntityToken,
    Observation,
    PendingChoice,
)
from hsbg.policy.encoder import (
    CAND_FEATURE_OFFSET,
    CAND_NUM_DIM,
    ENCODED_KEYS,
    NUM_ENTITIES,
    UNK_CARD_INDEX,
    ZONE_OFFSET,
    CardVocab,
    ObservationEncoder,
    collect_card_ids,
    entity_index,
)
from hsbg.policy.model import (
    CHECKPOINT_FORMAT_VERSION,
    OBS_SCHEMA_VERSION,
    CheckpointCompatibilityError,
    EntityTransformerPolicy,
    PolicyConfig,
    build_policy,
    load_policy_and_encoder,
    migrate_legacy_checkpoint,
)
from hsbg.policy.synthetic import (
    FAKE_CARD_IDS,
    FAKE_SECONDARY_IDS,
    random_observation,
)


# ══════════════════════════════════════════════════════════════════════
# fixtures / helpers
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def vocab() -> CardVocab:
    return CardVocab(list(FAKE_CARD_IDS) + list(FAKE_SECONDARY_IDS))


@pytest.fixture(scope="module")
def encoder(vocab: CardVocab) -> ObservationEncoder:
    return ObservationEncoder(vocab)


@pytest.fixture(scope="module")
def tiny_policy(encoder: ObservationEncoder) -> EntityTransformerPolicy:
    torch.manual_seed(0)
    cfg = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    return build_policy(encoder, config=cfg)


def _kind_value(kind) -> str:
    return getattr(kind, "value", str(kind))


def _board_obs(n: int = 3) -> Observation:
    tokens = tuple(
        EntityToken(
            card_id=FAKE_CARD_IDS[i], card_type=CARD_TYPE_MINION,
            zone=ZONE_BOARD, slot=i, atk=2 + i, health=3 + i, tier=2,
        )
        for i in range(n)
    )
    return Observation(turn=4, board=tokens, candidates=())


def _dark_gift_obs(gift_ids=("FAKE_GIFT_000", "FAKE_GIFT_001", None)) -> Observation:
    """模拟 env 的 Dark Gift 选择步（options 主 id + extra.secondary_id）。"""
    options = tuple(
        EntityToken(
            card_id=FAKE_CARD_IDS[i], card_type=CARD_TYPE_MINION,
            zone=ZONE_CHOICE, slot=i, atk=3, health=4, tier=3,
        )
        for i in range(len(gift_ids))
    )
    obs = Observation(
        turn=6,
        phase=PHASE_CHOICE,
        pending_choice=PendingChoice(kind="dark_gift", options=options, for_agent=True),
        candidates=tuple(
            CandidateAction(kind="choose", option=i) for i in range(len(options))
        ),
    )
    obs.extra = {
        "pending_choice_options": [
            {
                "index": i,
                "card_id": options[i].card_id,
                "secondary_id": gid,
                "label": None,
                "name": f"Option{i}",
                "secondary_name": None,
                "cost": 3,
            }
            for i, gid in enumerate(gift_ids)
        ]
    }
    return obs


# ══════════════════════════════════════════════════════════════════════
# 1) 13 种动作 kind / MOVE_MINION 编码
# ══════════════════════════════════════════════════════════════════════


def test_action_kind_count_and_move_minion_index_is_appended() -> None:
    assert NUM_ACTION_KINDS == 13
    assert len(ACTION_KIND_INDEX) == 13
    # 既有 12 类索引不变（稳定契约：只允许末尾追加）
    assert ACTION_KIND_INDEX["buy"] == 0
    assert ACTION_KIND_INDEX["choose"] == 11
    assert ACTION_KIND_INDEX["move_minion"] == 12
    assert sorted(ACTION_KIND_INDEX.values()) == list(range(13))
    # 候选特征 kind one-hot 宽度随 NUM_ACTION_KINDS 动态变化（v2=38 → v3=39）
    assert CAND_NUM_DIM - NUM_ACTION_KINDS == 26


def test_encode_move_minion_candidate(encoder: ObservationEncoder) -> None:
    obs = _board_obs(3)
    obs.candidates = (
        CandidateAction(
            kind=ActionKind.MOVE_MINION,
            src_zone=ZONE_BOARD, src_slot=1, position=0,
        ),
        CandidateAction(kind=ActionKind.END_TURN),
    )
    enc = encoder.encode_obs(obs)
    kind_off = CAND_FEATURE_OFFSET["kind"]

    assert int(enc["cand_kind"][0]) == ACTION_KIND_INDEX["move_minion"] == 12
    assert int(enc["cand_kind"][1]) == ACTION_KIND_INDEX["end_turn"]
    assert (enc["cand_kind"] < NUM_ACTION_KINDS).all()
    # move_minion 的 one-hot 落在第 13 位；不会与 choose(11) / 其它列混淆
    assert enc["cand_num"][0, kind_off + 12] == 1.0
    assert enc["cand_num"][0, kind_off + 11] == 0.0
    assert enc["cand_num"][0, kind_off:kind_off + NUM_ACTION_KINDS].sum() == 1.0
    # position = 目标槽位（0..len(board)-1），src = 被移动随从
    assert enc["cand_num"][0, CAND_FEATURE_OFFSET["has_position"]] == 1.0
    assert enc["cand_num"][0, CAND_FEATURE_OFFSET["position"]] == pytest.approx(0.0)
    assert enc["cand_src"][0] == entity_index(ZONE_BOARD, 1)
    assert enc["cand_num"][0, CAND_FEATURE_OFFSET["has_src"]] == 1.0
    # 越界 src 不崩（防御性）
    bad = _board_obs(1)
    bad.candidates = (CandidateAction(kind="move_minion", src_zone=ZONE_BOARD,
                                      src_slot=9, position=0),)
    enc_bad = encoder.encode_obs(bad)
    assert enc_bad["cand_num"][0, CAND_FEATURE_OFFSET["has_src"]] == 0.0
    assert np.isfinite(enc_bad["cand_num"]).all()


def test_forward_batch_containing_move_candidates(
    encoder: ObservationEncoder, tiny_policy: EntityTransformerPolicy
) -> None:
    rng = np.random.default_rng(20261022)
    obs_list = []
    for _ in range(6):
        obs = random_observation(rng, card_ids=FAKE_CARD_IDS)
        board = tuple(
            EntityToken(card_id=FAKE_CARD_IDS[i], card_type=CARD_TYPE_MINION,
                        zone=ZONE_BOARD, slot=i, atk=1, health=2, tier=2)
            for i in range(2)
        )
        obs.board = board
        n_keep = min(len(obs.candidates), 4)
        obs.candidates = obs.candidates[:n_keep] + (
            CandidateAction(kind="move_minion", src_zone=ZONE_BOARD,
                            src_slot=0, position=1),
            CandidateAction(kind="move_minion", src_zone=ZONE_BOARD,
                            src_slot=1, position=0),
        )
        obs_list.append(obs)
    batch = encoder.collate(obs_list)
    n_move = int((batch["cand_kind"] == ACTION_KIND_INDEX["move_minion"]).sum().item())
    assert n_move >= len(obs_list)  # 每个样本至少 1 个 move 候选进入编码

    tiny_policy.eval()
    with torch.no_grad():
        logits, value = tiny_policy(batch)
        actions, logp, value2 = tiny_policy.act(batch)
    n = len(obs_list)
    assert logits.shape == (n, CANDIDATE_MAX)
    assert value.shape == (n,)
    assert torch.isfinite(logits).all()
    assert torch.isfinite(value).all()
    assert torch.isfinite(logp).all()
    mask = batch["cand_mask"].gather(1, actions.unsqueeze(-1)).squeeze(-1)
    assert bool((mask > 0.5).all())


# ══════════════════════════════════════════════════════════════════════
# 2) pending_choice_options → entity_secondary
# ══════════════════════════════════════════════════════════════════════


def test_secondary_ids_encoded_for_choice_options(
    encoder: ObservationEncoder, vocab: CardVocab
) -> None:
    obs = _dark_gift_obs()
    enc = encoder.encode_obs(obs)
    off = ZONE_OFFSET[ZONE_CHOICE]
    assert "entity_secondary" in ENCODED_KEYS
    assert set(enc) == set(ENCODED_KEYS)
    assert enc["entity_secondary"].shape == (NUM_ENTITIES,)
    # 第 0/1 个选项有已知 gift_id；第 2 个 None → 0
    assert int(enc["entity_secondary"][off]) == vocab.index("FAKE_GIFT_000")
    assert int(enc["entity_secondary"][off + 1]) == vocab.index("FAKE_GIFT_001")
    assert int(enc["entity_secondary"][off + 2]) == 0
    # card_id（主 id）仍走 entity_card，没有被 secondary 覆盖
    assert int(enc["entity_card"][off]) == vocab.index(FAKE_CARD_IDS[0])
    assert int(enc["entity_card"][off + 1]) == vocab.index(FAKE_CARD_IDS[1])
    # 只有 choice 区非 0
    assert int((enc["entity_secondary"] != 0).sum()) == 2
    # 动态词表也能收集到 gift_id（否则策略只能看到 <UNK>）
    ids = collect_card_ids(obs)
    assert "FAKE_GIFT_000" in ids and "FAKE_GIFT_001" in ids


def test_secondary_unknown_maps_to_unk(encoder: ObservationEncoder) -> None:
    obs = _dark_gift_obs(("NOT_IN_VOCAB_GIFT", None))
    enc = encoder.encode_obs(obs)
    off = ZONE_OFFSET[ZONE_CHOICE]
    assert int(enc["entity_secondary"][off]) == UNK_CARD_INDEX


def test_v2_observation_without_extra_encodes_zeros(
    encoder: ObservationEncoder,
) -> None:
    obs = _dark_gift_obs()
    obs.extra = {}  # 模拟 obs v2：没有 pending_choice_options
    enc = encoder.encode_obs(obs)
    assert int((enc["entity_secondary"] != 0).sum()) == 0
    # 选择区实体本身仍正常编码
    assert int(enc["entity_mask"].sum()) == 3


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"pending_choice_options": None},
        {"pending_choice_options": "not-a-list"},
        {"pending_choice_options": {"secondary_id": "x"}},
        {"pending_choice_options": [None, {}, {"secondary_id": 123}]},
        {"pending_choice_options": [
            {"secondary_id": ("a", "b")},
            {"secondary_id": ["a"]},
            {"secondary_id": {"x": 1}},
        ]},
        {"pending_choice_options": [
            {"index": 0, "card_id": FAKE_CARD_IDS[0], "secondary_id": "X"} for _ in range(10)
        ]},
    ],
)
def test_malformed_choice_options_never_crash(
    encoder: ObservationEncoder,
    tiny_policy: EntityTransformerPolicy,
    extra,
) -> None:
    obs = _dark_gift_obs()
    obs.extra = dict(extra)
    enc = encoder.encode_obs(obs)
    for key, arr in enc.items():
        assert np.isfinite(arr).all(), key
    batch = encoder.collate([obs, _dark_gift_obs(), random_observation(
        np.random.default_rng(0), card_ids=FAKE_CARD_IDS)])
    tiny_policy.eval()
    with torch.no_grad():
        logits, value = tiny_policy(batch)
    assert torch.isfinite(logits).all() and torch.isfinite(value).all()


def test_forward_actually_consumes_secondary_id(
    encoder: ObservationEncoder, tiny_policy: EntityTransformerPolicy
) -> None:
    """同一批观测只有 gift_id 不同 → choice 实体表示应不同（编码生效）。"""
    obs_a = _dark_gift_obs(("FAKE_GIFT_000", None))
    obs_b = _dark_gift_obs(("FAKE_GIFT_001", None))
    batch = encoder.collate([obs_a, obs_b])
    tiny_policy.eval()
    with torch.no_grad():
        out = tiny_policy.forward_full(batch)
    slot = ZONE_OFFSET[ZONE_CHOICE]
    rep = out["entity_reps"][:, slot, :]
    assert not torch.allclose(rep[0], rep[1])
    # 相同 gift_id 的两次编码 → 表示完全一致（确定性）
    batch_same = encoder.collate([obs_a, _dark_gift_obs(("FAKE_GIFT_000", None))])
    with torch.no_grad():
        out_same = tiny_policy.forward_full(batch_same)
    rep_same = out_same["entity_reps"][:, slot, :]
    assert torch.allclose(rep_same[0], rep_same[1], atol=1e-6)


def test_synthetic_observations_cover_v3_fields() -> None:
    rng = np.random.default_rng(3)
    obs_list = [random_observation(rng, card_ids=FAKE_CARD_IDS) for _ in range(200)]
    kinds = {_kind_value(c.kind) for obs in obs_list for c in obs.candidates}
    assert "move_minion" in kinds
    choices = [o for o in obs_list if o.pending_choice is not None]
    assert choices
    for obs in choices:
        assert obs.version == Observation.version
        meta = obs.extra["pending_choice_options"]
        assert len(meta) == len(obs.pending_choice.options)
        for i, item in enumerate(meta):
            assert item["index"] == i
            assert item["card_id"] == obs.pending_choice.options[i].card_id


# ══════════════════════════════════════════════════════════════════════
# 3) 旧（obs v2）checkpoint 兼容性
# ══════════════════════════════════════════════════════════════════════


def _write_legacy_v2_checkpoint(
    tmp_path, encoder: ObservationEncoder
) -> tuple:
    """构造一个观测 v2 结构的旧 ckpt（12 kinds / cand_num 38 维 / 无 obs_version）。"""
    torch.manual_seed(123)
    cfg_now = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    legacy_cfg = PolicyConfig.from_dict(
        {
            **cfg_now.to_dict(),
            "num_action_kinds": 12,
            "cand_num_dim": CAND_NUM_DIM - 1,
        }
    )
    legacy_policy = EntityTransformerPolicy(legacy_cfg)
    payload = {
        "format": "hsbg.policy.EntityTransformerPolicy",
        "format_version": 1,
        "policy_config": legacy_policy.config.to_dict(),
        "encoder_dims": legacy_policy.config.encoder_dims().as_dict(),
        "vocab": encoder.vocab.to_dict(),
        "state_dict": legacy_policy.state_dict(),
        "meta": {"trainer": "ppo", "note": "obs-v2-legacy"},
    }
    path = tmp_path / "legacy_v2_policy.pt"
    torch.save(payload, path)
    return path, legacy_policy


def test_legacy_checkpoint_strict_mode_rejected_with_migration_instructions(
    tmp_path, encoder: ObservationEncoder
) -> None:
    path, _ = _write_legacy_v2_checkpoint(tmp_path, encoder)
    with pytest.raises(CheckpointCompatibilityError) as exc_info:
        EntityTransformerPolicy.load(path, allow_legacy=False)
    msg = str(exc_info.value)
    assert "v2" in msg and "v3" in msg
    assert "MOVE_MINION" in msg
    assert "POLICY_OBS_V3" in msg
    assert "migrate_legacy_checkpoint" in msg and "allow_legacy" in msg
    # 评测/续训统一入口同样支持严格模式（不会静默按 12 kind 推理）
    with pytest.raises(CheckpointCompatibilityError):
        load_policy_and_encoder(path, allow_legacy=False)
    # 默认（allow_legacy=None）：迁移 + UserWarning，产物仍可用
    with pytest.warns(UserWarning, match="MOVE_MINION"):
        default_policy = EntityTransformerPolicy.load(path)
    assert default_policy.config.num_action_kinds == NUM_ACTION_KINDS
    assert default_policy.meta.get("legacy_migrated") is True


def test_legacy_checkpoint_allow_legacy_migrates_in_memory(
    tmp_path, encoder: ObservationEncoder
) -> None:
    path, legacy_policy = _write_legacy_v2_checkpoint(tmp_path, encoder)
    old_state = legacy_policy.state_dict()
    policy = EntityTransformerPolicy.load(path, allow_legacy=True)

    assert policy.config.num_action_kinds == NUM_ACTION_KINDS == 13
    assert policy.config.cand_num_dim == CAND_NUM_DIM
    assert policy.meta.get("legacy_migrated") is True
    migration = policy.meta["legacy_migration"]
    assert migration["from_num_action_kinds"] == 12
    assert migration["from_cand_num_dim"] == CAND_NUM_DIM - 1
    assert migration["from_format_version"] == 1
    # kind embedding：旧 12 行原样保留，第 13 行=旧行均值（不是随机大值）
    assert policy.kind_emb.num_embeddings == NUM_ACTION_KINDS
    assert torch.equal(
        policy.kind_emb.weight[:12], old_state["kind_emb.weight"]
    )
    assert torch.allclose(
        policy.kind_emb.weight[12], old_state["kind_emb.weight"].mean(dim=0)
    )
    # cand_num_mlp：kind 列 12→13，MOVE_MINION 新列权重 0，其后 26 列右移
    w_new = policy.cand_num_mlp[0].weight
    w_old = old_state["cand_num_mlp.0.weight"]
    assert w_new.shape == (32, CAND_NUM_DIM)
    assert torch.equal(w_new[:, :12], w_old[:, :12])
    assert float(w_new[:, 12].abs().sum().detach()) == 0.0
    assert torch.equal(w_new[:, 13:], w_old[:, 12:])
    # 迁移后编码器与新模型对齐，v3 batch 能正常前向
    enc = policy.make_encoder()
    assert enc.dims.num_action_kinds == NUM_ACTION_KINDS
    assert enc.dims.cand_num_dim == CAND_NUM_DIM
    batch = enc.collate([_dark_gift_obs(), _board_obs_with_move()])
    policy.eval()
    with torch.no_grad():
        logits, value = policy(batch)
    assert logits.shape == (2, CANDIDATE_MAX)
    assert torch.isfinite(logits).all() and torch.isfinite(value).all()


def test_migrate_legacy_checkpoint_writes_loadable_v3_file(
    tmp_path, encoder: ObservationEncoder
) -> None:
    path, _ = _write_legacy_v2_checkpoint(tmp_path, encoder)
    out = migrate_legacy_checkpoint(path, tmp_path / "migrated_v3.pt")
    assert out.exists()
    payload = torch.load(out, map_location="cpu", weights_only=False)
    assert payload["format_version"] == CHECKPOINT_FORMAT_VERSION == 2
    assert payload["obs_version"] == OBS_SCHEMA_VERSION == Observation.version == 3
    assert payload["num_action_kinds"] == NUM_ACTION_KINDS
    assert payload["policy_config"]["num_action_kinds"] == NUM_ACTION_KINDS
    assert payload["encoder_dims"]["num_action_kinds"] == NUM_ACTION_KINDS
    assert payload["encoder_dims"]["cand_num_dim"] == CAND_NUM_DIM
    assert payload["meta"]["legacy_migration"]["from_num_action_kinds"] == 12
    # 迁移后默认加载（无需 allow_legacy）
    policy, enc = load_policy_and_encoder(out)
    assert policy.config.cand_num_dim == CAND_NUM_DIM
    batch = enc.collate([_dark_gift_obs(), _board_obs_with_move()])
    policy.eval()
    with torch.no_grad():
        logits, _ = policy(batch)
    assert torch.isfinite(logits).all()
    # 默认输出路径 = 同目录 <stem>_obs_v3.pt
    default_out = migrate_legacy_checkpoint(path)
    assert default_out.name == "legacy_v2_policy_obs_v3.pt"
    assert default_out.exists()


def test_new_checkpoint_records_obs_schema_version(
    tmp_path, encoder: ObservationEncoder, tiny_policy: EntityTransformerPolicy
) -> None:
    path = tmp_path / "v3_policy.pt"
    tiny_policy.save(path)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    assert payload["format_version"] == CHECKPOINT_FORMAT_VERSION
    assert payload["obs_version"] == OBS_SCHEMA_VERSION
    assert payload["num_action_kinds"] == NUM_ACTION_KINDS
    assert payload["encoder_dims"]["num_action_kinds"] == NUM_ACTION_KINDS
    loaded, enc = load_policy_and_encoder(path)
    assert loaded.encoder_dims.num_action_kinds == NUM_ACTION_KINDS
    batch = enc.collate([_dark_gift_obs()])
    tiny_policy.eval()
    loaded.eval()
    with torch.no_grad():
        logits_a, value_a = tiny_policy(batch)
        logits_b, value_b = loaded(batch)
    assert torch.allclose(logits_a, logits_b, atol=1e-6)
    assert torch.allclose(value_a, value_b, atol=1e-6)


def test_future_obs_version_checkpoint_is_rejected(
    tmp_path, encoder: ObservationEncoder
) -> None:
    policy = build_policy(
        encoder,
        config=PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64),
    )
    path = policy.save(tmp_path / "future.pt")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    payload["obs_version"] = OBS_SCHEMA_VERSION + 1
    torch.save(payload, path)
    with pytest.raises(CheckpointCompatibilityError, match="obs_version"):
        EntityTransformerPolicy.load(path, allow_legacy=True)


# 供迁移后前向用的 move 候选观测（与 _board_obs 区分命名，便于阅读）
def _board_obs_with_move() -> Observation:
    obs = _board_obs(2)
    obs.candidates = (
        CandidateAction(kind="move_minion", src_zone=ZONE_BOARD, src_slot=0, position=1),
        CandidateAction(kind="end_turn"),
    )
    return obs
