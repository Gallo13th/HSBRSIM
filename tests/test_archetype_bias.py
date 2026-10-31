"""流派软偏置（``hsbg/az/train/archetype_bias.py``）单测。

覆盖：
- ``parse_obs`` 只读 features/cards（turn/tier/gold/lobby/战团/酒馆/手牌/英雄）；
- ``action_type_of`` 的逐段映射（含 Buy 随从/法术、Play 手牌、机械动作不计）；
- ``bias_from_pref``：**只加不减**、非法位恒 0、单动作上限 ``coef*MAX_TOTAL``、
  空偏好表 → 全 0；
- 两段式检测：流派级 / 种族族回退 / 低置信不偏置，统计字段口径；
- 英雄 OOV → ``other`` 位；
- ``coef=0`` 默认关闭：不构造对象、不新增 meta 键、决策序列**逐位等价**旧路径；
- ``aggregate_archetype_bias`` 多 worker 汇总。
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from hsbg.az.train.archetype_bias import (
    ACTION_TYPES,
    A_BUY,
    A_END,
    A_PLAY,
    MAX_TOTAL,
    ArchetypeBias,
    ArchetypeHistory,
    ArchetypeObs,
    FEATURE_DIM,
    FEATURE_VERSION,
    HERO_VOCAB_SIZE,
    N_TRIBES,
    RHYTHM_TYPES,
    SoftmaxModel,
    TRIBES,
    action_type_of,
    aggregate_archetype_bias,
    bias_from_pref,
    build_vector,
    bucket_key,
    feature_names,
    parse_obs,
    save_model,
)
from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.env.obs_std import (
    GLOBAL_FIELD_INDEX,
    GLOBAL_FIELD_SCALE,
    ITEM_F,
    ITEM_IS_MINION,
    ITEM_MINION,
    MINION_F,
    MINION_RACES,
    SLICE_BOARD,
    SLICE_GLOBAL,
    SLICE_CARD_SHOP,
    SLICE_HAND,
    SLICE_SHOP,
)


# ══════════════════════════════════════════════════════════════════════════
# 合成观测（不依赖引擎）
# ══════════════════════════════════════════════════════════════════════════
def _blank_features() -> np.ndarray:
    return np.zeros(OBS_FLOATS, dtype=np.float32)


def _set_global(f: np.ndarray, turn: float, tier: float, gold: float) -> None:
    gi = GLOBAL_FIELD_INDEX
    f[gi["turn"]] = turn / GLOBAL_FIELD_SCALE["turn"]
    f[gi["tier"]] = tier / GLOBAL_FIELD_SCALE["tier"]
    f[gi["gold"]] = gold / GLOBAL_FIELD_SCALE["gold"]


def _set_minion(block: np.ndarray, race: str, atk: float = 1.0) -> None:
    block[0] = 1.0            # present
    block[1] = atk
    block[MINION_RACES + TRIBES.index(race)] = 1.0


def _set_item(block: np.ndarray, race: str | None, is_minion: bool = True) -> None:
    block[0] = 1.0                               # present
    block[ITEM_IS_MINION] = 1.0 if is_minion else 0.0
    if is_minion and race:
        block[ITEM_MINION + MINION_RACES + TRIBES.index(race)] = 1.0


def _features(*, turn: int = 5, tier: int = 2, gold: float = 5.0,
              board: str = "DRAGON", shop: str | None = "DRAGON",
              n_shop: int = 4, hand: str | None = None,
              lobby: tuple = ("DRAGON", "MECHANICAL")) -> np.ndarray:
    f = _blank_features()
    _set_global(f, turn, tier, gold)
    if board:
        _set_minion(f[SLICE_BOARD.start: SLICE_BOARD.start + MINION_F], board)
    for i in range(n_shop):
        blk = f[SLICE_SHOP.start + i * ITEM_F: SLICE_SHOP.start + (i + 1) * ITEM_F]
        _set_item(blk, shop)
    if hand:
        blk = f[SLICE_HAND.start: SLICE_HAND.start + ITEM_F]
        _set_item(blk, hand)
    for r in lobby:
        f[SLICE_GLOBAL.start + 42 + TRIBES.index(r)] = 1.0
    return f


def _cards(hero_index: int = 0) -> np.ndarray:
    # 观测卡牌块是 i32（``obs_arrays`` 按 "<i4" 解释），dtype 必须一致
    c = np.zeros(OBS_CARDS, dtype=np.int32)
    c[0] = int(hero_index)
    return c


def _mask(*actions: int) -> np.ndarray:
    m = np.zeros(N_ACTIONS, dtype=bool)
    for a in actions:
        m[int(a)] = True
    return m


# ══════════════════════════════════════════════════════════════════════════
# 1. 观测解析
# ══════════════════════════════════════════════════════════════════════════
def test_parse_obs_reads_only_visible_fields():
    f = _features(turn=7, tier=3, gold=8.0, board="MECHANICAL",
                  shop="PIRATE", hand="MECHANICAL",
                  lobby=("DRAGON", "MECHANICAL", "PIRATE"))
    obs = parse_obs(f, _cards(hero_index=12), hero_id_of=lambda i: "HERO_X")
    assert (obs.turn, obs.tier) == (7, 3)
    assert obs.gold == pytest.approx(8.0)
    assert obs.hero_id == "HERO_X"
    assert obs.board_tribes[TRIBES.index("MECHANICAL")] == pytest.approx(1.0)
    assert obs.board_tribes.sum() == pytest.approx(1.0)
    assert obs.shop_present.sum() == 4
    assert obs.shop_minion.sum() == 4
    assert obs.shop_tribes[:, TRIBES.index("PIRATE")].sum() == pytest.approx(4.0)
    assert obs.hand_minion[0] and obs.hand_tribes[0, TRIBES.index("MECHANICAL")] == 1.0
    lobby = [TRIBES[i] for i in np.flatnonzero(obs.lobby)]
    assert lobby == ["DRAGON", "MECHANICAL", "PIRATE"]


def test_parse_obs_without_hero_lookup_and_bad_dims():
    obs = parse_obs(_features(), _cards(), hero_id_of=None)
    assert obs.hero_id == ""
    with pytest.raises(ValueError):
        parse_obs(np.zeros(10, np.float32), _cards())
    with pytest.raises(ValueError):
        parse_obs(_features(), np.zeros(3, np.int64))


# ══════════════════════════════════════════════════════════════════════════
# 2. 动作 → 类型
# ══════════════════════════════════════════════════════════════════════════
def test_action_type_mapping():
    obs = parse_obs(_features(shop="MECHANICAL"), _cards())
    assert action_type_of(A_END, obs) == "end_turn"
    assert action_type_of(1, obs) == "reroll"
    assert action_type_of(2, obs) == "freeze"
    assert action_type_of(3, obs) == "upgrade"
    assert action_type_of(4, obs) == "hero_power"
    assert action_type_of(6, obs) == "dark_gift"
    assert action_type_of(A_BUY, obs) == "buy_minion"
    assert action_type_of(A_BUY + 3, obs) == "buy_minion"
    assert action_type_of(16, obs) == "sell"
    # 机械动作不计（人工日志没有对应行，计进去会造成训练/推理口径漂移）
    assert action_type_of(7, obs) is None          # cancel
    assert action_type_of(30, obs) is None         # choose
    assert action_type_of(196, obs) is None        # move
    assert action_type_of(23, obs) is None         # activate
    assert action_type_of(126, obs) == "play_minion"   # magnetize 归到打出


def test_action_type_spell_and_hand():
    f = _features(shop=None)
    # 手牌槽 0 = 法术（非随从）
    blk = f[SLICE_HAND.start: SLICE_HAND.start + ITEM_F]
    _set_item(blk, None, is_minion=False)
    obs = parse_obs(f, _cards())
    assert action_type_of(A_PLAY, obs) == "play_spell"
    blk2 = f[SLICE_SHOP.start: SLICE_SHOP.start + ITEM_F]
    _set_item(blk2, None, is_minion=False)
    obs2 = parse_obs(f, _cards())
    assert action_type_of(A_BUY, obs2) == "buy_spell"


# ══════════════════════════════════════════════════════════════════════════
# 3. 特征构造
# ══════════════════════════════════════════════════════════════════════════
def test_feature_vector_shape_and_names():
    obs = parse_obs(_features(), _cards())
    st = ArchetypeHistory()
    st.observe("g", 0, obs)
    x = st.vector("g", 0, obs)
    assert x.shape == (FEATURE_DIM,)
    assert np.all(np.isfinite(x))
    names = feature_names()
    assert len(names) == FEATURE_DIM
    assert names[0] == "n_actions"


def test_history_accumulates_actions_once_per_turn():
    obs = parse_obs(_features(turn=5, tier=1, gold=4.0), _cards())
    hist = ArchetypeHistory()
    for _ in range(3):
        hist.observe("g", 0, obs)          # 同 turn 多次 observe：gold/tier 只记一次
    assert hist._get("g", 0).gold_n == 1
    for a in (A_END, 1, 3, A_BUY):
        hist.note_action("g", 0, a)
    st = hist._get("g", 0)
    assert st.n == 4
    assert st.type_counts[ACTION_TYPES.index("end_turn")] == 1
    assert st.type_counts[ACTION_TYPES.index("reroll")] == 1
    assert st.type_counts[ACTION_TYPES.index("upgrade")] == 1
    assert st.type_counts[ACTION_TYPES.index("buy_minion")] == 1
    # 买到的种族进入 flow（买 slot 0 = MECHANICAL/Minion）
    assert st.flow.sum() == pytest.approx(1.0)
    x = hist.vector("g", 0, obs)
    assert x[0] == pytest.approx(np.log1p(4))


def test_history_state_isolated_per_game_and_seat():
    obs = parse_obs(_features(turn=5), _cards())
    hist = ArchetypeHistory()
    hist.observe(1, 0, obs)
    hist.observe(2, 0, obs)
    hist.note_action(1, 0, A_BUY)
    hist.note_action(2, 0, A_END)
    assert hist._get(1, 0).type_counts[ACTION_TYPES.index("buy_minion")] == 1
    assert hist._get(2, 0).type_counts[ACTION_TYPES.index("buy_minion")] == 0


# ══════════════════════════════════════════════════════════════════════════
# 4. 偏置向量规则
# ══════════════════════════════════════════════════════════════════════════
def _pref(rates: dict | None = None, buy: dict | None = None,
          top_cards: dict | None = None) -> dict:
    return {
        "n": 100, "turns": 20,
        "rates": {t: 0.0 for t in ACTION_TYPES},
        "per_turn": rates or {},
        "buy_tribe": buy or {},
        "top_cards": top_cards or {},
    }


def test_bias_only_adds_and_never_masks():
    obs = parse_obs(_features(turn=5, shop="MECHANICAL"), _cards())
    mask = _mask(A_END, 1, 3, A_BUY, A_BUY + 1)
    pref = _pref(rates={"upgrade": 0.9, "reroll": 0.1, "hero_power": 0.0},
                 buy={"MECHANICAL": 0.8})
    base = _pref(rates={"upgrade": 0.2, "reroll": 0.5, "hero_power": 0.1},
                 buy={"MECHANICAL": 0.1})
    b = bias_from_pref(pref, base, obs, mask, coef=0.5)
    assert b.shape == (N_ACTIONS,)
    assert np.all(b >= 0.0)                      # 只加不减
    assert np.all(b[~mask] == 0.0)               # 非法位不碰
    assert b[3] > 0.0 and b[1] == 0.0            # upgrade 加、reroll 相对更低不减
    assert b[A_BUY] > 0.0                        # 种族匹配的买位加
    assert b[A_BUY + 1] > 0.0                    # 同种族别的槽位同样匹配
    assert b.max() <= 0.5 * MAX_TOTAL + 1e-6


def test_bias_zero_when_no_gain():
    obs = parse_obs(_features(turn=5), _cards())
    mask = _mask(A_END, 3, A_BUY)
    pref = _pref(rates={"upgrade": 0.1}, buy={"DRAGON": 0.2})
    base = _pref(rates={"upgrade": 0.2}, buy={"DRAGON": 0.2})
    assert not np.any(bias_from_pref(pref, base, obs, mask, coef=1.0))


def test_bias_coef_zero_is_all_zero():
    obs = parse_obs(_features(), _cards())
    mask = _mask(A_END, 3)
    pref = _pref(rates={"upgrade": 9.0}, buy={"DRAGON": 9.0})
    base = _pref(rates={"upgrade": 0.0}, buy={"DRAGON": 0.0})
    assert not np.any(bias_from_pref(pref, base, obs, mask, coef=0.0))


def test_bias_card_bonus_uses_shop_card_ids():
    obs = parse_obs(_features(turn=5, shop="MECHANICAL"), _cards())
    mask = _mask(A_END, A_BUY)
    pref = _pref(buy={"MECHANICAL": 0.5}, top_cards={"CARD_HIT": 0.2})
    base = _pref(buy={"MECHANICAL": 0.1})
    cards = _cards()
    cards[SLICE_CARD_SHOP.start] = 7     # 酒馆 0 号槽有卡（下标 > 0 才能查 id）
    hit = bias_from_pref(pref, base, obs, mask, coef=1.0,
                         card_index_of=lambda i: "CARD_HIT", cards=cards)
    miss = bias_from_pref(pref, base, obs, mask, coef=1.0,
                          card_index_of=lambda i: "OTHER", cards=cards)
    assert hit[A_BUY] > miss[A_BUY]
    # 卡牌分项只加不减，且总 bias 不超过 coef*MAX_TOTAL
    assert hit[A_BUY] <= 1.0 * MAX_TOTAL + 1e-6


# ══════════════════════════════════════════════════════════════════════════
# 5. 两段式检测 + 统计（合成表/模型，不依赖仓库制品）
# ══════════════════════════════════════════════════════════════════════════
def _write_artifacts(tmp_path: str, *, arch_bias: float = 12.0,
                     min_prob_ok: float = 0.99) -> tuple[str, str]:
    """写一个极小的合成偏好表 + 分类器（流派类固定占优，便于确定性断言）。"""
    buckets = [bucket_key(i) for i in range(6)] + ["all"]
    base = {}
    for b in buckets:
        base[b] = {
            "n": 100, "turns": 20, "rate_keys": list(ACTION_TYPES),
            "rates": {t: 0.05 for t in ACTION_TYPES},
            "per_turn": {"upgrade": 0.2, "reroll": 0.5, "hero_power": 0.1},
            "buy_tribe": {"DRAGON": 0.5, "MECHANICAL": 0.5},
            "board_tribe": {"DRAGON": 1.0},
        }
    pref = {}
    for b in buckets:
        pref[b] = {
            "n": 100, "turns": 20, "rate_keys": list(ACTION_TYPES),
            "rates": {t: 0.05 for t in ACTION_TYPES},
            "per_turn": {"upgrade": 0.8, "reroll": 0.1, "hero_power": 0.1},
            "buy_tribe": {"DRAGON": 0.9, "MECHANICAL": 0.1},
            "board_tribe": {"DRAGON": 1.0},
            "top_cards": {},
        }
    table = {
        "schema": "hsbg.archetype_table", "version": 1,
        "feature_version": FEATURE_VERSION, "feature_dim": FEATURE_DIM,
        "tribes": list(TRIBES), "turn_buckets": [[1, 4], [5, 6], [7, 8],
                                                 [9, 10], [11, 12], [13, 15]],
        "action_types": list(ACTION_TYPES), "rhythm_types": list(RHYTHM_TYPES),
        "head_archetypes": ["dragon_shield"], "hero_vocab": [],
        "baseline": base,
        "archetypes": {"dragon_shield": {"support": 10, "tribe_family": "dragon",
                                         "head": True, "pref": pref}},
        "tribes": {"dragon": {"support": 10, "pref": pref}},
    }
    tpath = os.path.join(tmp_path, "table.json")
    with open(tpath, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False)
    # 分类器：让流派类 "dragon_shield" 稳定占优（b 大），种族类 "dragon" 同理
    mean = np.zeros(FEATURE_DIM)
    std = np.ones(FEATURE_DIM)
    d = FEATURE_DIM
    W_a = np.zeros((d, 3))
    b_a = np.asarray([arch_bias, 0.0, 0.0])
    arch = SoftmaxModel(classes=("dragon_shield", "mech_apm", "other"),
                        W=W_a, b=b_a, mean=mean, std=std, temp=1.0)
    W_t = np.zeros((d, 3))
    b_t = np.asarray([arch_bias, 0.0, 0.0])
    tribe = SoftmaxModel(classes=("dragon", "mechanical", "beast"),
                         W=W_t, b=b_t, mean=mean, std=std, temp=1.0)
    mpath = os.path.join(tmp_path, "model.npz")
    save_model(mpath, tribe=tribe, arch=arch, hero_vocab=[], mean=mean, std=std,
               meta={"arch_top1_cv": 0.5})
    return tpath, mpath


def test_detection_archetype_level_and_stats(tmp_path):
    tpath, mpath = _write_artifacts(str(tmp_path))
    ab = ArchetypeBias(table_path=tpath, model_path=mpath, coef=0.5, min_prob=0.6,
                       card_index_of=lambda i: "")
    mask = _mask(A_END, 1, 3, A_BUY)
    b = ab.bias(_features(turn=6, shop="DRAGON"), _cards(), mask,
                game_id=1, seat=0)
    assert b is not None and b.shape == (N_ACTIONS,)
    meta = ab.to_meta()
    assert meta["archetype_detected"] == 1
    assert meta["archetype_name"] == "dragon_shield"
    assert meta["archetype_level_archetype"] == 1
    assert meta["archetype_bias_applied"] == 1
    assert meta["bias_applied"] == 1              # 任务书约定的短名
    assert meta["archetype_mean_prob"] > 0.9


def test_detection_falls_back_to_tribe(tmp_path):
    """流派类概率不足（other 占优）但种族族达标 → 用种族级表。"""
    tpath, mpath = _write_artifacts(str(tmp_path), arch_bias=12.0)
    ab = ArchetypeBias(table_path=tpath, model_path=mpath, coef=0.5, min_prob=0.6,
                       card_index_of=lambda i: "")
    # 让流派头类变成 other：把模型换成 other 占优
    class _M:
        pass
    other = SoftmaxModel(classes=("dragon_shield", "other"), W=np.zeros((FEATURE_DIM, 2)),
                         b=np.asarray([0.0, 12.0]), mean=np.zeros(FEATURE_DIM),
                         std=np.ones(FEATURE_DIM))
    ab.arch_model = other
    mask = _mask(A_END, 3, A_BUY)
    b = ab.bias(_features(turn=6, shop="DRAGON"), _cards(), mask, game_id=2, seat=0)
    assert b is not None
    meta = ab.to_meta()
    assert meta["archetype_level_tribe"] == 1
    assert meta["archetype_name"] == "dragon"


def test_low_confidence_no_bias(tmp_path):
    tpath, mpath = _write_artifacts(str(tmp_path), arch_bias=0.0)  # 均匀分布
    ab = ArchetypeBias(table_path=tpath, model_path=mpath, coef=5.0, min_prob=0.99,
                       card_index_of=lambda i: "")
    mask = _mask(A_END, 3, A_BUY)
    assert ab.bias(_features(), _cards(), mask, game_id=3, seat=0) is None
    meta = ab.to_meta()
    assert meta["archetype_detected"] == 0
    assert meta["archetype_bias_applied"] == 0
    assert meta["archetype_level_none"] == 1


def test_missing_archetype_in_table_falls_back(tmp_path):
    tpath, mpath = _write_artifacts(str(tmp_path))
    table = json.load(open(tpath, encoding="utf-8"))
    table["archetypes"].pop("dragon_shield")
    with open(tpath, "w", encoding="utf-8") as f:
        json.dump(table, f)
    ab = ArchetypeBias(table_path=tpath, model_path=mpath, coef=0.5, min_prob=0.6,
                       card_index_of=lambda i: "")
    mask = _mask(A_END, 3)
    b = ab.bias(_features(turn=6, shop="DRAGON"), _cards(), mask, game_id=4, seat=0)
    # 流派表缺失 → 回退种族族（dragon）→ 仍然给 bias
    assert b is not None
    assert ab.to_meta()["archetype_level_tribe"] == 1


def test_hero_oov_sets_other_bit():
    obs = parse_obs(_features(), _cards(hero_index=5),
                    hero_id_of=lambda i: "UNKNOWN_HERO")
    x = build_vector(ArchetypeHistory()._get("g", 0), obs,
                     hero_vocab=["HERO_A", "HERO_B"])
    hero_block = x[-HERO_VOCAB_SIZE - 1:]
    assert hero_block[HERO_VOCAB_SIZE] == 1.0        # other 位
    assert hero_block[:HERO_VOCAB_SIZE].sum() == 0.0


def test_model_version_mismatch_raises(tmp_path):
    tpath, mpath = _write_artifacts(str(tmp_path))
    with np.load(mpath) as z:
        payload = {k: z[k] for k in z.files}
    payload["feature_version"] = np.int64(FEATURE_VERSION + 1)
    bad = os.path.join(str(tmp_path), "bad.npz")
    np.savez(bad, **payload)
    with pytest.raises(ValueError):
        ArchetypeBias(table_path=tpath, model_path=bad, coef=0.5)


# ══════════════════════════════════════════════════════════════════════════
# 6. 与 PPO 策略接线：coef=0 逐位等价
# ══════════════════════════════════════════════════════════════════════════
class _DummyModel:
    def eval(self):
        return self

    def to(self, device):
        return self


class _StubEval:
    """确定性 stub：优先 Upgrade，其次 EndTurn；记录收到的 bias。"""

    name = "stub"

    def __init__(self) -> None:
        self.seen_bias = []

    @staticmethod
    def _pick(mask):
        legal = np.flatnonzero(np.asarray(mask, dtype=bool))
        for a in (3, 0):
            if a in set(int(x) for x in legal):
                return int(a)
        return int(legal[-1]) if legal.size else 0

    def act(self, features, cards, mask, temperature=1.0, seed=None, bias=None):
        self.seen_bias.append(None if bias is None else np.array(bias, copy=True))
        return self._pick(mask), 0.0, 0.0

    def act_batch(self, features, cards, mask, temperature=1.0, seed=None,
                  bias=None):
        m2 = np.atleast_2d(np.asarray(mask, dtype=bool))
        acts = np.asarray([self._pick(m) for m in m2], dtype=np.int64)
        self.seen_bias.append(None if bias is None else np.array(bias, copy=True))
        return (acts, np.zeros(len(acts), np.float32),
                np.zeros(len(acts), np.float32))


class _FakeGame:
    """只提供 policy 需要的 observe/legal_mask/turn。"""

    def __init__(self, mask=None, turn: int = 5) -> None:
        self.turn = int(turn)
        self._mask = _mask(*([A_END, 1, 3, A_BUY])) if mask is None else np.asarray(mask)
        self._f = _features(turn=self.turn)
        self._c = _cards()

    def observe(self, seat: int):
        return self._f.tobytes(), self._c.tobytes()

    def legal_mask(self, seat: int):
        return self._mask.astype(np.uint8).tobytes()


def _make_policy(*, coef: float = 0.0, table: str = "", model: str = "",
                 eval_fn=None):
    from hsbg.az.train.ppo import CollectConfig, PPOSelfPlayPolicy
    cfg = CollectConfig(archetype_bias_coef=float(coef),
                        archetype_table=str(table), archetype_model=str(model))
    return PPOSelfPlayPolicy(_DummyModel(), device="cpu", config=cfg,
                             eval_fn=eval_fn, seed=7, move_model=False)


def test_coef_zero_is_legacy_and_bitwise():
    ev0, ev1 = _StubEval(), _StubEval()
    p0 = _make_policy(coef=0.0, eval_fn=ev0)
    p1 = _make_policy(coef=0.0, eval_fn=ev1)
    assert p0._abias is None
    assert p0.archetype_bias_meta() == {}
    g0, g1 = _FakeGame(), _FakeGame()
    seq0, seq1 = [], []
    for _ in range(3):
        d0 = p0.decide(g0, 0)
        d1 = p1.decide(g1, 0)
        seq0.append((int(d0.action), float(d0.info["logprob"])))
        seq1.append((int(d1.action), float(d1.info["logprob"])))
    assert seq0 == seq1
    # 关闭时连 bias 参数都不传（旧 eval_fn 签名也兼容）
    assert all(b is None for b in ev0.seen_bias)
    assert all(b is None for b in ev1.seen_bias)


def test_coef_positive_passes_bias_to_eval_and_stays_legal(tmp_path):
    tpath, mpath = _write_artifacts(str(tmp_path))
    ev = _StubEval()
    p = _make_policy(coef=0.5, table=tpath, model=mpath, eval_fn=ev)
    assert p._abias is not None
    g = _FakeGame()
    d = p.decide(g, 0)
    assert ev.seen_bias and ev.seen_bias[0] is not None
    b = ev.seen_bias[0]
    mask = _mask(A_END, 1, 3, A_BUY)
    assert np.all(b >= 0.0) and np.all(b[~mask] == 0.0)
    # 动作仍合法（偏置不屏蔽任何动作，选动作的仍是原策略）
    assert bool(mask[int(d.action)])
    meta = p.archetype_bias_meta()
    assert meta["archetype_bias"] and meta["archetype_decisions"] == 1
    p.reset()
    assert p.archetype_bias_meta()["archetype_decisions"] == 1  # 累计统计跨局保留
    assert not p._abias.history._h                              # 逐局历史已清空


def test_aggregate_meta_sums_workers():
    a = {"archetype_bias": True, "archetype_bias_coef": 0.5,
         "archetype_min_prob": 0.6, "archetype_decisions": 10,
         "archetype_detected": 4, "archetype_bias_applied": 3,
         "archetype_level_archetype": 1, "archetype_level_tribe": 3,
         "archetype_level_none": 6, "archetype_bias_actions": 9,
         "archetype_names": {"dragon": 3, "mech": 1},
         "archetype_mean_prob": 0.8, "archetype_bias_sum": 1.5}
    b = {"archetype_bias": True, "archetype_bias_coef": 0.5,
         "archetype_min_prob": 0.6, "archetype_decisions": 6,
         "archetype_detected": 2, "archetype_bias_applied": 2,
         "archetype_level_archetype": 2, "archetype_level_tribe": 0,
         "archetype_level_none": 4, "archetype_bias_actions": 4,
         "archetype_names": {"mech": 3}, "archetype_mean_prob": 0.9,
         "archetype_bias_sum": 0.5}
    out = aggregate_archetype_bias([a, b])
    assert out["archetype_decisions"] == 16
    assert out["archetype_detected"] == 6
    assert out["archetype_bias_applied"] == 5
    assert out["bias_applied"] == 5
    assert out["archetype_names"] == {"dragon": 3, "mech": 4}
    assert out["archetype_name"] == "mech"
    assert out["archetype_mean_prob"] == pytest.approx((0.8 * 4 + 0.9 * 2) / 6)
    assert aggregate_archetype_bias([{}, {"x": 1}]) == {}
