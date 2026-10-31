"""流派（archetype）偏置优化后的**逐位等价**测试。

对照实现（``*_ref``）是优化前逐行拷贝的版本；两者必须给出**逐位相同**的结果：

1. ``parse_obs``（board/shop/hand 种族块）—— 物品块改成步长 gather 后；
2. ``build_vector`` —— 节奏块向量化 + ``FLOW_DECAY`` 幂表 + hero 预映射后；
3. ``bias_from_pref`` —— 整块 argmax 替代逐格 argmax 后；
4. ``ArchetypeBias.bias`` —— 输入哈希缓存开/关输出与统计口径必须一致。
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, Optional, Tuple

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytest.importorskip("hsbg_engine")

from hsbg.az.train import archetype_bias as AB  # noqa: E402


# ────────────────────── 优化前实现的逐行拷贝（参考） ──────────────────────
def _minion_tribes_ref(f: np.ndarray, base: int) -> np.ndarray:
    return np.asarray(f[base + AB.MINION_RACES: base + AB.MINION_RACES + AB.N_TRIBES],
                      dtype=np.float32)


def _item_blocks_ref(f: np.ndarray, sl: slice, n: int):
    tribes = np.zeros((n, AB.N_TRIBES), dtype=np.float32)
    is_minion = np.zeros((n,), dtype=bool)
    present = np.zeros((n,), dtype=bool)
    off = int(sl.start)
    for i in range(n):
        b = off + i * AB.ITEM_F
        present[i] = float(f[b]) > 0.5
        is_minion[i] = float(f[b + AB.ITEM_IS_MINION]) > 0.5
        if is_minion[i]:
            tribes[i] = _minion_tribes_ref(f, b + AB.ITEM_MINION)
    return tribes, is_minion, present


def parse_obs_ref(features, cards, *, hero_id_of=None):
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    c = np.asarray(cards, dtype=np.int64).reshape(-1)
    gi = AB.GLOBAL_FIELD_INDEX
    turn = int(round(float(f[gi["turn"]]) * AB.GLOBAL_FIELD_SCALE["turn"]))
    tier = int(round(float(f[gi["tier"]]) * AB.GLOBAL_FIELD_SCALE["tier"]))
    gold = float(f[gi["gold"]]) * AB.GLOBAL_FIELD_SCALE["gold"]
    lobby = np.asarray(
        f[AB.SLICE_GLOBAL.start + 42: AB.SLICE_GLOBAL.start + 42 + AB.N_TRIBES],
        dtype=np.float32).copy()
    board = np.zeros(AB.N_TRIBES, dtype=np.float32)
    off = int(AB.SLICE_BOARD.start)
    for i in range(AB.N_BOARD):
        b = off + i * AB.MINION_F
        if float(f[b]) > 0.5:
            board += _minion_tribes_ref(f, b)
    board_total = float(board.sum())
    if board_total > 0:
        board /= board_total
    shop_t, shop_m, shop_p = _item_blocks_ref(f, AB.SLICE_SHOP, AB.N_SHOP)
    hand_t, hand_m, hand_p = _item_blocks_ref(f, AB.SLICE_HAND, AB.N_HAND)
    hero = ""
    if hero_id_of is not None:
        try:
            idx = int(c[0])
            if idx > 0:
                hero = str(hero_id_of(idx) or "")
        except Exception:  # noqa: BLE001
            hero = ""
    return AB.ArchetypeObs(
        turn=max(0, turn), tier=max(0, tier), gold=float(gold), lobby=lobby,
        board_tribes=board, shop_tribes=shop_t, shop_minion=shop_m,
        shop_present=shop_p, hand_tribes=hand_t, hand_minion=hand_m,
        hand_present=hand_p, hero_id=hero)


def build_vector_ref(st, obs, *, hero_vocab=()):
    x = np.zeros(AB.FEATURE_DIM, dtype=np.float32)
    off = 0
    n = int(st.n)
    turn = max(1, int(obs.turn))
    x[off] = math.log1p(n)
    off += 1
    x[off] = turn / 15.0
    off += 1
    x[off] = n / float(turn)
    off += 1
    if n > 0:
        x[off: off + AB.N_ACTION_TYPES] = st.type_counts / float(n)
    off += AB.N_ACTION_TYPES
    for ti in range(AB.N_RHYTHM):
        for b in range(AB.N_BUCKETS):
            lo, hi = AB.TURN_BUCKETS[b]
            width = float(hi - lo + 1)
            x[off + ti * AB.N_BUCKETS + b] = st.rhythm[ti, b] / width
    off += AB.N_RHYTHM * AB.N_BUCKETS
    flow_total = float(st.flow.sum())
    if flow_total > 0:
        x[off: off + AB.N_TRIBES] = st.flow / flow_total
    off += AB.N_TRIBES
    if st.flow_events:
        acc = np.zeros(AB.N_TRIBES, dtype=np.float32)
        for ev_turn, ev_t in st.flow_events:
            w = float(AB.FLOW_DECAY) ** max(0, turn - int(ev_turn))
            acc[int(ev_t) % AB.N_TRIBES] += w
        tot = float(acc.sum())
        if tot > 0:
            x[off: off + AB.N_TRIBES] = acc / tot
    off += AB.N_TRIBES
    x[off: off + AB.N_TRIBES] = obs.board_tribes
    off += AB.N_TRIBES
    shop = obs.shop_tribes * obs.shop_minion.reshape(-1, 1)
    shop_total = float(shop.sum())
    if shop_total > 0:
        x[off: off + AB.N_TRIBES] = shop.sum(axis=0) / shop_total
    off += AB.N_TRIBES
    x[off: off + AB.N_BUCKETS] = st.tier_curve
    off += AB.N_BUCKETS
    x[off] = float(obs.tier)
    off += 1
    x[off] = float(st.max_tier)
    off += 1
    x[off] = (st.gold_sum / st.gold_n) if st.gold_n else 0.0
    off += 1
    x[off] = float(obs.gold)
    off += 1
    x[off: off + AB.N_TRIBES] = obs.lobby
    off += AB.N_TRIBES
    other = AB.HERO_VOCAB_SIZE
    idx = -1
    if obs.hero_id:
        try:
            idx = (int(hero_vocab.index(obs.hero_id))
                   if obs.hero_id in hero_vocab else -1)
        except ValueError:
            idx = -1
    if 0 <= idx < AB.HERO_VOCAB_SIZE:
        x[off + idx] = 1.0
    else:
        x[off + other] = 1.0
    off += AB.HERO_VOCAB_SIZE + 1
    assert off == AB.FEATURE_DIM
    return x


def bias_from_pref_ref(pref, base, obs, mask, *, coef,
                       card_index_of=None, cards=None):
    bias = np.zeros(245, dtype=np.float32)
    c = float(coef)
    if c <= 0.0:
        return bias
    rates = pref.get("per_turn") or pref.get("rates") or {}
    brates = base.get("per_turn") or base.get("rates") or {}
    for cat, acts in (("upgrade", (AB.A_UPGRADE,)),
                      ("reroll", (AB.A_REFRESH,)),
                      ("hero_power", tuple(range(AB.A_HERO_POWER,
                                                 AB.A_HERO_POWER + AB.N_POWERS)))):
        g = AB._rate_gain(float(rates.get(cat, 0.0) or 0.0),
                          float(brates.get(cat, 0.0) or 0.0))
        if g > 0.0:
            for a in acts:
                bias[a] += c * g
    w_buy = pref.get("buy_tribe") or {}
    b_buy = base.get("buy_tribe") or {}
    top_cards = {str(k): float(v) for k, v in (pref.get("top_cards") or {}).items()}
    wa = [float(w_buy.get(t, 0.0) or 0.0) for t in AB.TRIBES]
    wb = [float(b_buy.get(t, 0.0) or 0.0) for t in AB.TRIBES]
    for slot in range(AB.N_SHOP):
        if not bool(obs.shop_present[slot]) or not bool(obs.shop_minion[slot]):
            continue
        t = int(np.argmax(obs.shop_tribes[slot]))
        g = AB._tribe_gain(wa, wb, t)
        if g > 0.0:
            bias[AB.A_BUY + slot] += c * AB.BUY_W * g
        if card_index_of is not None and cards is not None and top_cards:
            try:
                idx = int(np.asarray(cards).reshape(-1)[AB.SLICE_CARD_SHOP.start + slot])
                cid = str(card_index_of(idx)) if idx > 0 else ""
            except Exception:  # noqa: BLE001
                cid = ""
            share = float(top_cards.get(cid, 0.0) or 0.0)
            if share >= AB.CARD_MIN_SHARE:
                bias[AB.A_BUY + slot] += c * AB.CARD_W * min(1.0, share / AB.CARD_SCALE)
    for h in range(AB.N_HAND):
        if not bool(obs.hand_present[h]) or not bool(obs.hand_minion[h]):
            continue
        t = int(np.argmax(obs.hand_tribes[h]))
        g = AB._tribe_gain(wa, wb, t)
        if g <= 0.0:
            continue
        base_a = AB.A_PLAY + h * AB.N_POS
        bias[base_a: base_a + AB.N_POS] += c * AB.PLAY_FACTOR * g
    m = np.asarray(mask, dtype=bool).reshape(-1)
    bias[~m] = 0.0
    np.clip(bias, 0.0, c * AB.MAX_TOTAL, out=bias)
    return bias


# ─────────────────────────────── 观测样本 ───────────────────────────────
def _observations(n_seeds: int = 3, steps: int = 120):
    import hsbg_engine as E
    from hsbg.az.train.common import mask_from_bytes, obs_arrays

    out = []
    for s in range(int(n_seeds)):
        g = E.Game(seed=700 + s)
        guard = 0
        while not g.is_over() and guard < int(steps):
            acted = False
            for p in range(int(g.num_players)):
                if g.needs_action(p):
                    f, c = obs_arrays(g.observe(p))
                    out.append((f, c, mask_from_bytes(g.legal_mask(p))))
                    g.bot_play(p)
                    acted = True
                    guard += 1
                    break
            if not acted:
                break
    return out


def _check_obs_equal(a, b):
    for name in ("turn", "tier", "gold", "hero_id"):
        assert getattr(a, name) == getattr(b, name), name
    for name in ("lobby", "board_tribes", "shop_tribes", "shop_minion",
                 "shop_present", "hand_tribes", "hand_minion", "hand_present"):
        x, y = getattr(a, name), getattr(b, name)
        assert x.dtype == y.dtype, (name, x.dtype, y.dtype)
        assert np.array_equal(x, y), name


def test_parse_obs_matches_reference():
    obs_list = _observations()
    assert len(obs_list) > 20
    for f, c, _m in obs_list:
        new = AB.parse_obs(f, c)
        ref = parse_obs_ref(f, c)
        _check_obs_equal(new, ref)


def test_build_vector_matches_reference():
    rng = np.random.default_rng(0)
    obs_list = _observations(n_seeds=1, steps=40)
    vocab = tuple(f"hero_{i}" for i in range(20))
    for k in range(400):
        f, c, _m = obs_list[k % len(obs_list)]
        obs = AB.parse_obs(f, c)
        st = AB._Hist()
        st.n = int(rng.integers(0, 40))
        st.type_counts = (rng.random(AB.N_ACTION_TYPES) * 5).astype(np.float32)
        st.rhythm = (rng.random((AB.N_RHYTHM, AB.N_BUCKETS)) * 6).astype(np.float32)
        st.flow = (rng.random(AB.N_TRIBES) * 3).astype(np.float32)
        st.tier_curve = (rng.random(AB.N_BUCKETS) * 5).astype(np.float32)
        st.max_tier = int(rng.integers(0, 7))
        st.gold_sum = float(rng.random() * 100)
        st.gold_n = int(rng.integers(0, 20))
        ne = int(rng.integers(0, 12))
        st.flow_events = [(int(rng.integers(1, 16)), int(rng.integers(0, AB.N_TRIBES)))
                          for _ in range(ne)]
        if k % 3 == 0:
            obs = AB.ArchetypeObs(**{**obs.__dict__,
                                     "hero_id": str(vocab[int(rng.integers(0, 20))])})
        elif k % 3 == 1:
            obs = AB.ArchetypeObs(**{**obs.__dict__, "hero_id": "OOV_HERO"})
        new = AB.build_vector(st, obs, hero_vocab=vocab)
        ref = build_vector_ref(st, obs, hero_vocab=vocab)
        assert np.array_equal(new, ref), f"vector 不一致 @k={k}"


def test_bias_from_pref_matches_reference():
    ab = AB.ArchetypeBias(coef=0.5, min_prob=0.6)
    obs_list = _observations(n_seeds=1, steps=30)
    names = [c for c in ab.arch_model.classes if c != "other"] + \
            list(ab.tribe_model.classes)
    for k, (f, c, m) in enumerate(obs_list):
        obs = AB.parse_obs(f, c, hero_id_of=ab.card_id_of)
        for nm in names[:6]:
            for lvl in ("archetype", "tribe"):
                got = ab._pref_for(str(nm), level=lvl, b=AB.bucket_of(obs.turn))
                if got is None:
                    continue
                pref, base = got
                new = AB.bias_from_pref(pref, base, obs, m, coef=0.5,
                                        card_index_of=ab.card_id_of, cards=c)
                ref = bias_from_pref_ref(pref, base, obs, m, coef=0.5,
                                         card_index_of=ab.card_id_of, cards=c)
                assert np.array_equal(new, ref), (k, nm, lvl)


def test_bias_cache_is_transparent():
    """缓存开/关：bias 输出、统计、history 状态必须完全一致。"""
    obs_list = _observations(n_seeds=2, steps=80)
    on = AB.ArchetypeBias(coef=0.5, min_prob=0.6, cache=True)
    off = AB.ArchetypeBias(coef=0.5, min_prob=0.6, cache=False)
    acts = [0, 1, 40, 100, 200, 5, 6, 15]
    gi = 0
    for k, (f, c, m) in enumerate(obs_list):
        gid = f"g{gi}"
        seat = k % 8
        a = on.bias(f, c, m, game_id=gid, seat=seat)
        b = off.bias(f, c, m, game_id=gid, seat=seat)
        if a is None:
            assert b is None, k
        else:
            assert np.array_equal(a, b), k
        act = acts[k % len(acts)]
        on.note_action(act, game_id=gid, seat=seat)
        off.note_action(act, game_id=gid, seat=seat)
        if k % 40 == 39:
            gi += 1
    assert on.stats == off.stats
    assert on.cache_hits >= 0
    # 同输入重复调用 -> 必须命中缓存且结果一致
    f, c, m = obs_list[0]
    h0 = on.cache_hits
    x1 = on.bias(f, c, m, game_id="repeat", seat=0)
    x2 = on.bias(f, c, m, game_id="repeat", seat=0)
    if x1 is None:
        assert x2 is None
    else:
        assert np.array_equal(x1, x2)
    assert on.cache_hits > h0 or on.cache_misses == 0
