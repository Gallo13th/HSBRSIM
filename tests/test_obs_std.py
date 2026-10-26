"""标准观测 profile（``hsbg.env.obs_std``）金标回归。

在安装 ``taverngym`` 时运行（未安装自动 skip）：

1. ``layout()`` 的 32 项与上游 ``taverngym.layout()`` **逐项相等**；
2. ``OBS_FLOATS=3227`` / ``OBS_CARDS=124`` / ``N_ACTIONS=245`` / ``N_CARDS``
   与上游一致；
3. 浮点块/卡牌块切片连续覆盖整个向量、形状正确、字段偏移与 ``obs.rs`` 一致；
4. ``decode_blocks`` 能直接解码上游 ``Game.observe(seat)`` 的原始字节，返回
   只读块视图；输入非法时明确报错；
5. 与 ``hsbg.backends.taverngym_env`` 的内部布局推导交叉一致。

运行::

    python3 -m pytest tests/test_obs_std.py -q
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("taverngym")

import taverngym  # noqa: E402

from hsbg.env import obs_std as o  # noqa: E402


def _upstream_obs(seed: int = 0):
    """跑上游引擎到招募回合，返回 ``(game, features_bytes, cards_bytes)``。"""
    game = taverngym.Game(int(seed))
    for _ in range(40):
        for seat in range(game.num_players):
            if game.needs_action(seat):
                game.bot_play(seat)
        if game.turn >= 2 and game.needs_action(0):
            break
    features, cards = game.observe(0)
    return game, features, cards


# ══════════════════════════════════════════════════════════════════════
# 1. 金标对照上游 layout()
# ══════════════════════════════════════════════════════════════════════


class TestGoldLayout:
    def test_layout_matches_upstream(self):
        upstream = [list(item) for item in taverngym.layout()]
        std = [list(item) for item in o.layout()]
        assert std == upstream
        assert len(o.layout()) == 32

    def test_sizes_match_upstream(self):
        assert o.OBS_FLOATS == taverngym.OBS_FLOATS == 3227
        assert o.OBS_CARDS == taverngym.OBS_CARDS == 124
        assert o.N_ACTIONS == taverngym.N_ACTIONS == 245
        assert o.N_CARDS_REFERENCE == taverngym.N_CARDS == 3984
        assert o.EMPTY_CARD_INDEX == 0

    def test_named_constants_match_layout(self):
        upstream = dict(taverngym.layout())
        for name in (
            "MINION_F", "ITEM_F", "GLOBAL_F", "N_QUESTS", "QUEST_F",
            "N_SECRETS", "OPP_F", "N_OPP", "PENDING_KINDS", "N_SHOP",
            "N_BOARD", "N_HAND", "N_CHOICE", "N_POS", "N_POWERS",
            "A_END", "A_REFRESH", "A_FREEZE", "A_UPGRADE", "A_HERO_POWER",
            "A_DARK_GIFT", "A_CANCEL", "A_BUY", "A_SELL", "A_ACTIVATE",
            "A_CHOOSE", "A_PLAY", "A_MAGNETIZE", "A_MOVE",
            "N_ACTIONS", "OBS_FLOATS", "OBS_CARDS",
        ):
            assert getattr(o, name) == upstream[name], name


# ══════════════════════════════════════════════════════════════════════
# 2. 块切片 / 形状 / 字段偏移
# ══════════════════════════════════════════════════════════════════════


class TestBlockLayout:
    def test_float_blocks_cover_vector(self):
        expect = 0
        for name, sl, shape in o.FLOAT_BLOCKS:
            assert sl.start == expect, name
            assert sl.stop - sl.start == int(np.prod(shape)), name
            assert o.FLOAT_BLOCK_SLICES[name] == sl
            expect = sl.stop
        assert expect == o.OBS_FLOATS
        assert o.SLICE_GLOBAL == slice(0, 53)
        assert o.SLICE_QUESTS == slice(53, 59)
        assert o.SLICE_PENDING == slice(59, 68)
        assert o.SLICE_BOARD == slice(68, 68 + 7 * 31)
        assert o.SLICE_HAND == slice(285, 285 + 10 * 40)
        assert o.SLICE_SHOP == slice(685, 685 + 8 * 40)
        assert o.SLICE_CHOICES == slice(1005, 1005 + 16 * 40)
        assert o.SLICE_OPPONENTS == slice(1645, 1645 + 7 * 9)
        assert o.SLICE_OPP_BOARDS == slice(1708, 3227)

    def test_card_blocks_cover_vector(self):
        expect = 0
        for name, sl, shape in o.CARD_BLOCKS:
            assert sl.start == expect, name
            assert sl.stop - sl.start == int(np.prod(shape)), name
            assert o.CARD_BLOCK_SLICES[name] == sl
            expect = sl.stop
        assert expect == o.OBS_CARDS
        # 与上游 obs.rs 的 OBS_CARDS 注释顺序一致
        assert o.SLICE_CARD_HERO == slice(0, 1)
        assert o.SLICE_CARD_POWERS == slice(1, 3)
        assert o.SLICE_CARD_DEITY == slice(3, 4)
        assert o.SLICE_CARD_PENDING_SOURCE == slice(4, 5)
        assert o.SLICE_CARD_QUESTS == slice(5, 14)
        assert o.SLICE_CARD_SECRETS == slice(14, 19)
        assert o.SLICE_CARD_BOARD == slice(19, 26)
        assert o.SLICE_CARD_HAND == slice(26, 36)
        assert o.SLICE_CARD_SHOP == slice(36, 44)
        assert o.SLICE_CARD_CHOICES == slice(44, 60)
        assert o.SLICE_CARD_TRINKETS == slice(60, 68)
        assert o.SLICE_CARD_OPP_HEROES == slice(68, 75)
        assert o.SLICE_CARD_OPP_BOARDS == slice(75, 124)

    def test_block_shapes(self):
        shapes = o.block_shapes()
        assert shapes["global"] == (53,)
        assert shapes["quests"] == (3, 2)
        assert shapes["pending_kinds"] == (9,)
        assert shapes["board_minions"] == (7, 31)
        assert shapes["hand_items"] == (10, 40)
        assert shapes["shop_items"] == (8, 40)
        assert shapes["choice_items"] == (16, 40)
        assert shapes["opponents"] == (7, 9)
        assert shapes["opponent_boards"] == (7, 7, 31)
        assert shapes["card_quests"] == (3, 3)
        assert shapes["card_opp_boards"] == (7, 7)
        assert len(shapes) == len(o.FLOAT_BLOCKS) + len(o.CARD_BLOCKS)

    def test_field_offset_tables(self):
        assert len(o.GLOBAL_FIELD_NAMES) == 42
        assert len(o.GLOBAL_FIELD_INDEX) == 42
        assert o.GLOBAL_FIELD_INDEX["turn"] == 0
        assert o.GLOBAL_FIELD_INDEX["chronum"] == 41
        assert o.GLOBAL_LOBBY_RACES_START == 42
        assert len(o.RACE_NAMES) == o.RACES_COUNT == 11
        assert len(o.KEYWORD_NAMES) == 12
        assert len(o.PENDING_KIND_NAMES) == o.PENDING_KINDS == 9
        assert o.PENDING_KIND_NAMES[0] == "none"
        # MINION 块偏移（obs.rs push_minion）
        assert (o.MINION_PRESENT, o.MINION_ATK, o.MINION_HP,
                o.MINION_MAX_HP, o.MINION_TIER, o.MINION_GOLDEN,
                o.MINION_ATTACHED, o.MINION_SHIELD_HITS) == tuple(range(8))
        assert o.MINION_KEYWORDS == 8
        assert o.MINION_RACES == 8 + len(o.KEYWORD_NAMES) == 20
        # ITEM 块偏移（obs.rs push_item）
        assert o.ITEM_MINION == 9 and o.ITEM_MINION + o.MINION_F == o.ITEM_F
        assert (o.ITEM_PRESENT, o.ITEM_IS_MINION, o.ITEM_COST) == (0, 1, 2)
        assert o.SPELL_TIER == 13
        # OPP 块偏移（obs.rs opponents）
        assert (o.OPP_PRESENT, o.OPP_ALIVE, o.OPP_HEALTH, o.OPP_ARMOR,
                o.OPP_TIER, o.OPP_SEEN_BOARD_LEN, o.OPP_PLACEMENT,
                o.OPP_IS_LAST, o.OPP_IS_NEXT) == tuple(range(9))

    def test_global_scale_table(self):
        assert set(o.GLOBAL_FIELD_SCALE) <= set(o.GLOBAL_FIELD_NAMES)
        assert o.GLOBAL_FIELD_SCALE["turn"] == 20.0
        assert o.GLOBAL_FIELD_SCALE["health"] == 40.0
        assert o.GLOBAL_FIELD_SCALE["gold"] == 10.0
        # 布尔/枚举字段不缩放
        for name in ("me_alive", "frozen", "can_dark_gift", "won_last"):
            assert name not in o.GLOBAL_FIELD_SCALE


# ══════════════════════════════════════════════════════════════════════
# 3. decode_blocks：真实上游观测 + 输入形态 + 只读
# ══════════════════════════════════════════════════════════════════════


class TestDecodeBlocks:
    def test_decode_real_upstream_observation(self):
        game, fb, cb = _upstream_obs(seed=0)
        assert len(fb) == o.OBS_FLOATS * 4
        assert len(cb) == o.OBS_CARDS * 4
        blocks = o.decode_blocks(fb, cb)

        assert blocks["features"].shape == (o.OBS_FLOATS,)
        assert blocks["cards"].shape == (o.OBS_CARDS,)
        for name, _sl, shape in o.FLOAT_BLOCKS:
            assert blocks[name].shape == shape, name
            assert blocks[name].dtype == np.float32
        for name, _sl, shape in o.CARD_BLOCKS:
            assert blocks[name].shape == shape, name
            assert blocks[name].dtype == np.int32

        # 真实状态抽查：turn / 商店 / 棋盘 / 英雄
        assert round(float(blocks["global"][o.GLOBAL_FIELD_INDEX["turn"]]) * 20) \
            == int(game.turn)
        assert 0.0 <= float(blocks["global"][
            o.GLOBAL_FIELD_INDEX["health"]]) <= 1.0
        shop_present = float(blocks["shop_items"][:, o.ITEM_PRESENT].sum())
        assert 0 <= shop_present <= o.N_SHOP
        hero_card = int(blocks["card_hero"][0])
        assert hero_card == int(blocks["cards"][0])
        # pending one-hot 至多一个 1
        assert float(blocks["pending_kinds"].sum()) <= 1.0

    def test_accepts_bytes_ndarray_and_list(self):
        _game, fb, cb = _upstream_obs(seed=1)
        from_bytes = o.decode_blocks(fb, cb)
        from_np = o.decode_blocks(
            np.frombuffer(fb, dtype="<f4").copy(),
            np.frombuffer(cb, dtype="<i4").copy())
        from_list = o.decode_blocks(
            list(np.frombuffer(fb, dtype="<f4")),
            [int(v) for v in np.frombuffer(cb, dtype="<i4")])
        for name in ("features", "cards", "global", "board_minions",
                     "card_opp_boards"):
            assert np.array_equal(from_bytes[name], from_np[name]), name
            assert np.array_equal(from_bytes[name], from_list[name]), name

    def test_views_are_read_only(self):
        _game, fb, cb = _upstream_obs(seed=0)
        blocks = o.decode_blocks(fb, cb)
        for name, arr in blocks.items():
            assert arr.flags.writeable is False, name
            with pytest.raises(ValueError):
                arr[0] = 1
        # copy=True：独立只读副本
        copied = o.decode_blocks(fb, cb, copy=True)
        assert copied["global"].flags.writeable is False
        assert not np.shares_memory(copied["global"], blocks["global"])
        assert np.array_equal(copied["global"], blocks["global"])
        # 输入 bytes 本身不可变（只读视图不修改原数据）
        assert len(fb) == o.OBS_FLOATS * 4

    def test_invalid_inputs_raise(self):
        _game, fb, cb = _upstream_obs(seed=0)
        with pytest.raises(ValueError):
            o.decode_blocks(fb[:-4], cb)          # 长度不足
        with pytest.raises(ValueError):
            o.decode_blocks(fb, cb[:-4])
        with pytest.raises(ValueError):
            o.decode_blocks(b"\x00" * 3, cb)      # 非 4 字节对齐
        with pytest.raises(ValueError):
            o.decode_blocks(np.zeros(o.OBS_FLOATS, dtype=np.float64), cb)
        with pytest.raises(ValueError):
            o.decode_blocks(fb, np.zeros(o.OBS_CARDS, dtype=np.int64))

    def test_cross_check_taverngym_backend_layout(self):
        """与 TavernGym 参照后端内部布局推导（``_tg_layout``）逐项一致。"""
        from hsbg.backends.taverngym_env import _tg_layout  # noqa: PLC0415

        lay = _tg_layout()
        assert lay.minion_f == o.MINION_F
        assert lay.item_f == o.ITEM_F
        assert lay.global_f == o.GLOBAL_F
        assert lay.n_quests == o.N_QUESTS
        assert lay.quest_f == o.QUEST_F
        assert lay.n_secrets == o.N_SECRETS
        assert lay.opp_f == o.OPP_F
        assert lay.n_opp == o.N_OPP
        assert lay.pending_kinds == o.PENDING_KINDS
        assert lay.n_board == o.N_BOARD
        assert lay.n_hand == o.N_HAND
        assert lay.n_shop == o.N_SHOP
        assert lay.n_choice == o.N_CHOICE
        assert lay.n_pos == o.N_POS
        assert lay.n_powers == o.N_POWERS
        assert lay.obs_floats == o.OBS_FLOATS
        assert lay.obs_cards == o.OBS_CARDS
        # 浮点块偏移
        assert lay.off_quests == o.SLICE_QUESTS.start
        assert lay.off_pending == o.SLICE_PENDING.start
        assert lay.off_board == o.SLICE_BOARD.start
        assert lay.off_hand == o.SLICE_HAND.start
        assert lay.off_shop == o.SLICE_SHOP.start
        assert lay.off_choices == o.SLICE_CHOICES.start
        assert lay.off_opps == o.SLICE_OPPONENTS.start
        assert lay.off_opp_boards == o.SLICE_OPP_BOARDS.start
        # 卡牌块偏移
        assert lay.c_hero == o.SLICE_CARD_HERO.start
        assert lay.c_powers == o.SLICE_CARD_POWERS.start
        assert lay.c_deity == o.SLICE_CARD_DEITY.start
        assert lay.c_pending == o.SLICE_CARD_PENDING_SOURCE.start
        assert lay.c_quests == o.SLICE_CARD_QUESTS.start
        assert lay.c_secrets == o.SLICE_CARD_SECRETS.start
        assert lay.c_board == o.SLICE_CARD_BOARD.start
        assert lay.c_hand == o.SLICE_CARD_HAND.start
        assert lay.c_shop == o.SLICE_CARD_SHOP.start
        assert lay.c_choices == o.SLICE_CARD_CHOICES.start
        assert lay.c_trinkets == o.SLICE_CARD_TRINKETS.start
        assert lay.c_opp_heroes == o.SLICE_CARD_OPP_HEROES.start
        assert lay.c_opp_boards == o.SLICE_CARD_OPP_BOARDS.start
