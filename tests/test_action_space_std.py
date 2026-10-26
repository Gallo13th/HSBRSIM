"""标准动作空间（``hsbg.env.action_space_std``）金标回归。

本文件在安装 ``taverngym`` 时运行（未安装自动 skip）；核心断言是对上游
TavernGym 的**逐位对照**：

1. 0..244 的 ``action_name`` 与 ``taverngym.action_name(i)`` **完全相等**；
2. 常量（A_* / N_*）与 ``taverngym.layout()`` 的 32 项逐项相等；
3. ``decode→encode`` 全量恒等（含扩展段 245..265）；
4. 扩展动作段（UNFREEZE / 备用技能槽 / 备用选择槽）不越界、不覆盖标准段；
5. 与 legacy ``hsbg.env.spec.CandidateAction`` 的双向转换（含语义差异、
   非法输入、Observation 上下文）。

运行::

    python3 -m pytest tests/test_action_space_std.py -q
"""

from __future__ import annotations

import pytest

pytest.importorskip("taverngym")

import taverngym  # noqa: E402

from hsbg.env import action_space_std as a  # noqa: E402
from hsbg.env.spec import (  # noqa: E402
    CARD_TYPE_MINION,
    CARD_TYPE_SPELL,
    CandidateAction,
    EntityToken,
    Observation,
)

#: 上游 layout() 中属于动作空间的 15 个常量名
_AT_ACTION_LAYOUT_NAMES = (
    "A_END", "A_REFRESH", "A_FREEZE", "A_UPGRADE", "A_HERO_POWER",
    "A_DARK_GIFT", "A_CANCEL", "A_BUY", "A_SELL", "A_ACTIVATE", "A_CHOOSE",
    "A_PLAY", "A_MAGNETIZE", "A_MOVE", "N_ACTIONS",
)
#: 上游 layout() 中动作空间相关的规模常量名
_AT_ACTION_SIZE_NAMES = ("N_SHOP", "N_BOARD", "N_HAND", "N_CHOICE", "N_POS",
                         "N_POWERS")


# ══════════════════════════════════════════════════════════════════════
# 1. 金标对照上游
# ══════════════════════════════════════════════════════════════════════


class TestGoldStandard:
    def test_constants_match_upstream_layout(self):
        upstream = dict(taverngym.layout())
        for name in _AT_ACTION_LAYOUT_NAMES + _AT_ACTION_SIZE_NAMES:
            assert hasattr(a, name), f"缺少常量 {name}"
            assert getattr(a, name) == upstream[name], (
                f"{name}: std={getattr(a, name)} != AT={upstream[name]}")
        assert a.N_ACTIONS == taverngym.N_ACTIONS == 245
        assert a.N_STD_ACTIONS == 245

    def test_derived_constants_are_consistent(self):
        assert a.A_DARK_GIFT == a.A_HERO_POWER + a.N_POWERS
        assert a.A_CANCEL == a.A_DARK_GIFT + 1
        assert a.A_BUY == a.A_CANCEL + 1
        assert a.A_SELL == a.A_BUY + a.N_SHOP
        assert a.A_ACTIVATE == a.A_SELL + a.N_BOARD
        assert a.A_CHOOSE == a.A_ACTIVATE + a.N_BOARD
        assert a.A_PLAY == a.A_CHOOSE + a.N_CHOICE
        assert a.A_MAGNETIZE == a.A_PLAY + a.N_HAND * a.N_POS
        assert a.A_MOVE == a.A_MAGNETIZE + a.N_HAND * a.N_BOARD
        assert a.N_ACTIONS == a.A_MOVE + a.N_BOARD * a.N_BOARD

    def test_action_name_matches_upstream_for_all_245(self):
        mismatches = [
            (i, a.action_name(i), taverngym.action_name(i))
            for i in range(245) if a.action_name(i) != taverngym.action_name(i)
        ]
        assert mismatches == []
        # 抽样固定几个 Rust Debug 格式（防格式化实现漂移）
        assert a.action_name(0) == "EndTurn"
        assert a.action_name(4) == "HeroPower(0)"
        assert a.action_name(7) == "Cancel"
        assert a.action_name(46) == "Play { hand: 0, pos: 0 }"
        assert a.action_name(125) == "Play { hand: 9, pos: 7 }"
        assert a.action_name(126) == "Magnetize { hand: 0, board: 0 }"
        assert a.action_name(196) == "Move { from: 0, to: 0 }"
        assert a.action_name(244) == "Move { from: 6, to: 6 }"

    def test_action_name_rejects_invalid(self):
        with pytest.raises(ValueError):
            a.action_name(-1)
        with pytest.raises(ValueError):
            a.action_name(a.N_TOTAL_ACTIONS)
        with pytest.raises(TypeError):
            a.action_name("0")


# ══════════════════════════════════════════════════════════════════════
# 2. 编解码 / 段划分
# ══════════════════════════════════════════════════════════════════════


#: 每类动作的样例（覆盖标准段 + 扩展段）
_SAMPLE_ACTIONS = (
    a.EndTurn(), a.Refresh(), a.Freeze(), a.Upgrade(),
    a.HeroPower(0), a.HeroPower(1), a.HeroPower(2), a.HeroPower(5),
    a.DarkGift(), a.Cancel(),
    a.Buy(0), a.Buy(7), a.Sell(0), a.Sell(6),
    a.Activate(0), a.Activate(6),
    a.Choose(0), a.Choose(15), a.Choose(16), a.Choose(31),
    a.Play(hand=0, pos=0), a.Play(hand=9, pos=7),
    a.Magnetize(hand=0, board=0), a.Magnetize(hand=9, board=6),
    a.Move(src=0, to=0), a.Move(src=6, to=6),
    a.Unfreeze(), a.FreezeSlot(0), a.FreezeSlot(7),
)


class TestCodec:
    def test_encode_decode_roundtrip_all_indices(self):
        assert a.N_TOTAL_ACTIONS == 274
        for index in range(a.N_TOTAL_ACTIONS):
            action = a.decode(index)
            assert a.encode(action) == index, (
                f"索引 {index} → {action!r} → {a.encode(action)}")

    def test_each_action_type_roundtrip(self):
        for action in _SAMPLE_ACTIONS:
            index = a.encode(action)
            assert a.decode(index) == action
            assert a.action_name(index) == a.action_name(action)
            assert a.is_std_index(index) != a.is_extension_index(index)

    def test_decode_rejects_invalid(self):
        for bad in (-1, a.N_TOTAL_ACTIONS, 10 ** 6):
            with pytest.raises(ValueError):
                a.decode(bad)
        for bad in (True, "1", 1.5, None):
            with pytest.raises(TypeError):
                a.decode(bad)

    def test_encode_rejects_invalid_fields(self):
        for bad in (a.HeroPower(-1), a.HeroPower(6),
                    a.Buy(-1), a.Buy(a.N_SHOP), a.Sell(-1), a.Sell(a.N_BOARD),
                    a.Activate(-1), a.Activate(a.N_BOARD),
                    a.Choose(-1), a.Choose(a.N_CHOICES_TOTAL),
                    a.Play(hand=-1, pos=0), a.Play(hand=a.N_HAND, pos=0),
                    a.Play(hand=0, pos=a.N_POS),
                    a.Magnetize(hand=-1, board=0),
                    a.Magnetize(hand=0, board=a.N_BOARD),
                    a.Move(src=-1, to=0), a.Move(src=0, to=a.N_BOARD),
                    a.FreezeSlot(-1), a.FreezeSlot(a.N_FREEZE_SLOTS)):
            with pytest.raises(ValueError):
                a.encode(bad)
        with pytest.raises(ValueError):
            a.encode(object())  # type: ignore[arg-type]

    def test_segments_cover_all_indices_without_gap(self):
        expect = 0
        seen_names = set()
        for name, lo, hi, count, desc in a.SEGMENTS:
            assert lo == expect
            assert hi - lo == count > 0
            assert name not in seen_names
            seen_names.add(name)
            expect = hi
            if lo < a.N_STD_ACTIONS:
                assert hi <= a.N_STD_ACTIONS, f"标准段 {name} 越过 245"
        assert expect == a.N_TOTAL_ACTIONS
        # segment_of 边界
        assert a.segment_of(0) == "end_turn"
        assert a.segment_of(244) == "move"
        assert a.segment_of(245) == "unfreeze"
        assert a.segment_of(265) == "extra_choose"
        assert a.segment_of(266) == "freeze_slot"
        assert a.segment_of(273) == "freeze_slot"
        with pytest.raises(ValueError):
            a.segment_of(a.N_TOTAL_ACTIONS)


# ══════════════════════════════════════════════════════════════════════
# 3. 扩展动作段
# ══════════════════════════════════════════════════════════════════════


class TestExtensionActions:
    def test_standard_segment_is_frozen(self):
        """扩展段从 245 开始，且前 245 项索引/名字都不受扩展影响。"""
        assert a.A_EXT_BASE == a.N_ACTIONS == 245
        assert a.A_UNFREEZE == 245
        assert a.N_STD_ACTIONS == 245
        assert a.N_TOTAL_ACTIONS == a.N_STD_ACTIONS + a.N_EXT_ACTIONS
        # 扩展段整体在标准段之后
        for name, lo, hi, _count, _desc in a.SEGMENTS:
            if lo < a.N_STD_ACTIONS:
                assert hi <= a.N_STD_ACTIONS, name
            else:
                assert lo >= a.N_STD_ACTIONS, name

    def test_unfreeze(self):
        assert a.encode(a.Unfreeze()) == 245
        assert a.decode(245) == a.Unfreeze()
        assert a.action_name(245) == "Unfreeze"
        assert a.is_extension_index(245)
        assert not a.is_std_index(245)

    def test_reserved_extra_hero_power_slots(self):
        for slot in range(a.N_POWERS, a.N_EXTRA_POWER_SLOTS_MAX):
            action = a.HeroPower(slot)
            index = a.encode(action)
            assert a.A_EXTRA_POWER <= index < (
                a.A_EXTRA_POWER + a.N_EXTRA_POWER_SLOTS)
            assert a.decode(index) == action
            assert a.action_name(index) == f"HeroPower({slot})"

    def test_reserved_extra_choose_slots(self):
        for option in range(a.N_CHOICE, a.N_CHOICES_TOTAL):
            action = a.Choose(option)
            index = a.encode(action)
            assert a.A_EXTRA_CHOOSE <= index < (
                a.A_EXTRA_CHOOSE + a.N_EXTRA_CHOICE_SLOTS)
            assert a.decode(index) == action
            assert a.action_name(index) == f"Choose({option})"

    def test_extension_does_not_overlap_standard(self):
        ext_indices = [a.A_UNFREEZE]
        ext_indices += [a.A_EXTRA_POWER + k
                        for k in range(a.N_EXTRA_POWER_SLOTS)]
        ext_indices += [a.A_EXTRA_CHOOSE + k
                        for k in range(a.N_EXTRA_CHOICE_SLOTS)]
        ext_indices += [a.A_FREEZE_SLOT + k
                        for k in range(a.N_FREEZE_SLOTS)]
        assert all(i >= 245 for i in ext_indices)
        assert len(set(ext_indices)) == a.N_EXT_ACTIONS == 29
        assert max(ext_indices) == a.N_TOTAL_ACTIONS - 1 == 273
        # 扩展段 action_name 与标准段不混淆
        names = [a.action_name(i) for i in range(245, a.N_TOTAL_ACTIONS)]
        assert names[0] == "Unfreeze"
        assert names[-8:] == [f"FreezeSlot({k})" for k in range(8)]
        assert all(name for name in names)
        assert len(set(names)) == len(names)

    def test_freeze_slot(self):
        """P2-C OPS-02：按槽位冻结/解冻（8 槽 = 266..273）。"""
        assert a.A_FREEZE_SLOT == 266
        assert a.N_FREEZE_SLOTS == 8
        assert a.encode(a.FreezeSlot(0)) == 266
        assert a.encode(a.FreezeSlot(3)) == 269
        assert a.encode(a.FreezeSlot(7)) == 273
        for slot in range(a.N_FREEZE_SLOTS):
            index = a.encode(a.FreezeSlot(slot))
            assert 266 <= index < 274
            assert a.decode(index) == a.FreezeSlot(slot)
            assert a.action_name(index) == f"FreezeSlot({slot})"
            assert a.action_name(a.FreezeSlot(slot)) == f"FreezeSlot({slot})"
            assert a.is_extension_index(index)
            assert not a.is_std_index(index)
        # 与整馆 Freeze/Unfreeze 是相互独立的动作编号
        assert a.encode(a.Freeze()) == 2
        assert a.encode(a.Unfreeze()) == 245
        assert a.encode(a.FreezeSlot(0)) == 266


# ══════════════════════════════════════════════════════════════════════
# 4. 与 legacy CandidateAction 的转换
# ══════════════════════════════════════════════════════════════════════


def _ctx(**kwargs) -> a.CandidateContext:
    return a.CandidateContext(**kwargs)


class TestCandidateConversion:
    @pytest.mark.parametrize("candidate,expected", [
        (CandidateAction(kind="end_turn"), a.EndTurn()),
        (CandidateAction(kind="reroll"), a.Refresh()),
        (CandidateAction(kind="freeze"), a.Freeze()),
        (CandidateAction(kind="upgrade"), a.Upgrade()),
        (CandidateAction(kind="use_dark_gift"), a.DarkGift()),
        (CandidateAction(kind="buy", src_zone="tavern", src_slot=3),
         a.Buy(3)),
        (CandidateAction(kind="sell", src_zone="board", src_slot=2),
         a.Sell(2)),
        (CandidateAction(kind="activate", src_zone="board", src_slot=1),
         a.Activate(1)),
        (CandidateAction(kind="choose", option=4), a.Choose(4)),
        (CandidateAction(kind="hero_power"), a.HeroPower(0)),
        (CandidateAction(kind="play_minion", src_zone="hand", src_slot=2,
                         position=3), a.Play(hand=2, pos=3)),
        (CandidateAction(kind="play_minion", src_zone="hand", src_slot=1,
                         tgt_zone="board", tgt_slot=4, position=-1),
         a.Magnetize(hand=1, board=4)),
        (CandidateAction(kind="play_spell", src_zone="hand", src_slot=0),
         a.Play(hand=0, pos=0)),
        (CandidateAction(kind="move_minion", src_zone="board", src_slot=0,
                         position=5), a.Move(src=0, to=5)),
        (CandidateAction(kind="cancel"), a.Cancel()),
        (CandidateAction(kind="unfreeze"), a.Unfreeze()),
        (CandidateAction(kind="freeze_slot", src_zone="tavern",
                         src_slot=5), a.FreezeSlot(5)),
    ])
    def test_candidate_to_std(self, candidate, expected):
        assert a.candidate_to_std(candidate) == expected
        assert a.action_name(a.encode(expected)) == a.action_name(expected)

    def test_candidate_to_std_invalid(self):
        assert a.candidate_to_std(None) is None
        assert a.candidate_to_std(object()) is None
        assert a.candidate_to_std(CandidateAction(kind="bogus")) is None
        # 槽位越界 → None（不抛异常，便于批量转换）
        assert a.candidate_to_std(
            CandidateAction(kind="buy", src_slot=a.N_SHOP)) is None
        assert a.candidate_to_std(
            CandidateAction(kind="sell", src_slot=a.N_BOARD)) is None
        assert a.candidate_to_std(
            CandidateAction(kind="choose", option=a.N_CHOICES_TOTAL)) is None
        assert a.candidate_to_std(
            CandidateAction(kind="freeze_slot", src_slot=-1)) is None
        assert a.candidate_to_std(
            CandidateAction(kind="freeze_slot",
                            src_slot=a.N_FREEZE_SLOTS)) is None

    def test_std_to_candidate(self):
        cases = [
            (a.EndTurn(), "end_turn"),
            (a.Refresh(), "reroll"),
            (a.Freeze(), "freeze"),
            (a.Upgrade(), "upgrade"),
            (a.DarkGift(), "use_dark_gift"),
            (a.Cancel(), "cancel"),
            (a.Unfreeze(), "unfreeze"),
            (a.FreezeSlot(2), "freeze_slot"),
        ]
        for action, kind in cases:
            candidate = a.std_to_candidate(action)
            assert candidate is not None and candidate.kind == kind
        assert a.std_to_candidate(a.Buy(3)).signature() == CandidateAction(
            kind="buy", src_zone="tavern", src_slot=3).signature()
        assert a.std_to_candidate(a.Sell(2)).signature() == CandidateAction(
            kind="sell", src_zone="board", src_slot=2).signature()
        assert a.std_to_candidate(a.Choose(4)).signature() == CandidateAction(
            kind="choose", option=4).signature()
        assert a.std_to_candidate(a.Move(0, 5)).signature() == CandidateAction(
            kind="move_minion", src_zone="board", src_slot=0,
            position=5).signature()
        magnet = a.std_to_candidate(a.Magnetize(1, 4))
        assert magnet.kind == "play_minion" and magnet.tgt_zone == "board"
        assert magnet.tgt_slot == 4 and magnet.position == -1
        freeze_slot = a.std_to_candidate(a.FreezeSlot(2))
        assert freeze_slot.kind == "freeze_slot"
        assert freeze_slot.src_zone == "tavern" and freeze_slot.src_slot == 2

    def test_std_to_candidate_accepts_index_and_rejects_invalid(self):
        assert a.std_to_candidate(0).kind == "end_turn"
        assert a.std_to_candidate(11).signature() == a.std_to_candidate(
            a.Buy(3)).signature()
        for bad in (-1, a.N_TOTAL_ACTIONS, 10 ** 6):
            assert a.std_to_candidate(bad) is None

    def test_roundtrip_non_lossy_candidates(self):
        samples = [
            CandidateAction(kind="end_turn"),
            CandidateAction(kind="reroll"),
            CandidateAction(kind="freeze"),
            CandidateAction(kind="upgrade"),
            CandidateAction(kind="use_dark_gift"),
            CandidateAction(kind="buy", src_zone="tavern", src_slot=3),
            CandidateAction(kind="sell", src_zone="board", src_slot=2),
            CandidateAction(kind="activate", src_zone="board", src_slot=1),
            CandidateAction(kind="choose", option=4),
            CandidateAction(kind="play_minion", src_zone="hand", src_slot=2,
                             position=3),
            CandidateAction(kind="play_minion", src_zone="hand", src_slot=1,
                            tgt_zone="board", tgt_slot=4, position=-1),
            CandidateAction(kind="move_minion", src_zone="board", src_slot=0,
                            position=5),
            CandidateAction(kind="freeze_slot", src_zone="tavern", src_slot=5),
        ]
        for candidate in samples:
            action = a.candidate_to_std(candidate)
            assert action is not None, candidate
            back = a.std_to_candidate(action)
            assert back is not None, (candidate, action)
            assert back.signature() == candidate.signature(), (
                candidate, action, back)
        # play_spell 的反向需要卡牌类型上下文（AT 的 Play 不区分随从/法术）
        spell = CandidateAction(kind="play_spell", src_zone="hand",
                                src_slot=0)
        action = a.candidate_to_std(spell)
        assert action == a.Play(hand=0, pos=0)
        back = a.std_to_candidate(
            action, _ctx(hand_card_types=(CARD_TYPE_SPELL,)))
        assert back is not None and back.signature() == spell.signature()

    def test_play_spell_target_is_play_plus_choose(self):
        spell = CandidateAction(kind="play_spell", src_zone="hand",
                                src_slot=1, tgt_zone="board", tgt_slot=2)
        # 单项映射：只剩 Play（目标信息丢弃，AT 语义：目标走后续 Choose）
        assert a.candidate_to_std(spell) == a.Play(hand=1, pos=0)
        seq = a.candidate_to_std_sequence(
            spell, _ctx(target_option=3))
        assert seq == (a.Play(hand=1, pos=0), a.Choose(3))
        # 无上下文（target_option=-1）→ 单步
        assert a.candidate_to_std_sequence(spell) == (a.Play(hand=1, pos=0),)

    def test_battlecry_target_is_play_plus_choose(self):
        minion = CandidateAction(kind="play_minion", src_zone="hand",
                                 src_slot=0, position=2, tgt_zone="board",
                                 tgt_slot=1)
        assert a.candidate_to_std(minion) == a.Play(hand=0, pos=2)
        assert a.candidate_to_std_sequence(
            minion, _ctx(target_option=0)) == (
                a.Play(hand=0, pos=2), a.Choose(0))

    def test_append_position_uses_context_board_size(self):
        append = CandidateAction(kind="play_minion", src_zone="hand",
                                 src_slot=0, position=-1)
        # 无上下文 → pos=0（保守）
        assert a.candidate_to_std(append) == a.Play(hand=0, pos=0)
        assert a.candidate_to_std(append, _ctx(board_size=5)) == a.Play(
            hand=0, pos=5)

    def test_hero_power_slot_context(self):
        cand = CandidateAction(kind="hero_power")
        assert a.candidate_to_std(cand) == a.HeroPower(0)
        assert a.candidate_to_std(
            cand, _ctx(hero_power_slot=1)) == a.HeroPower(1)
        # 扩展槽（≥2）在 legacy 候选没有来源，但转换支持
        assert a.candidate_to_std(
            cand, _ctx(hero_power_slot=2)) == a.HeroPower(2)
        # 反向：主槽按 legacy 约定不带 src 字段
        assert a.std_to_candidate(a.HeroPower(0)).signature() == (
            CandidateAction(kind="hero_power").signature())
        # 扩展槽反向带 src_zone/src_slot（legacy 约定，便于环境接入）
        back = a.std_to_candidate(a.HeroPower(3))
        assert back.kind == "hero_power" and back.src_slot == 3

    def test_play_reverse_uses_hand_card_types(self):
        ctx = _ctx(hand_card_types=("", CARD_TYPE_SPELL, CARD_TYPE_MINION))
        spell = a.std_to_candidate(a.Play(hand=1, pos=0), ctx)
        assert spell.kind == "play_spell" and spell.src_slot == 1
        minion = a.std_to_candidate(a.Play(hand=2, pos=3), ctx)
        assert minion.kind == "play_minion"
        assert minion.position == 3
        # 未提供类型 → 默认按随从
        default = a.std_to_candidate(a.Play(hand=1, pos=0))
        assert default.kind == "play_minion"

    def test_make_context_from_observation(self):
        obs = Observation(
            turn=1,
            board=(EntityToken(card_id="A", card_type=CARD_TYPE_MINION),
                   EntityToken(card_id="B", card_type=CARD_TYPE_MINION)),
            hand=(EntityToken(card_id="SP", card_type=CARD_TYPE_SPELL),),
        )
        ctx = a.make_context(obs)
        assert ctx.board_size == 2
        assert ctx.hand_card_types == (CARD_TYPE_SPELL,)
        spell = a.std_to_candidate(a.Play(hand=0, pos=0), obs)
        assert spell.kind == "play_spell"
        append = CandidateAction(kind="play_minion", src_zone="hand",
                                 src_slot=0, position=-1)
        assert a.candidate_to_std(append, obs) == a.Play(hand=0, pos=2)
        with pytest.raises(TypeError):
            a.make_context(object())

    def test_cross_check_taverngym_backend_module(self):
        """与 ``hsbg.backends.taverngym_env`` 的 245 维映射约定一致。"""
        from hsbg.backends.taverngym_env import (  # noqa: PLC0415
            _action_name,
            _tg_layout,
        )

        for index in range(245):
            assert a.action_name(index) == _action_name(index)
        lay = _tg_layout()
        assert lay.n_actions == a.N_ACTIONS
        assert lay.a_end == a.A_END and lay.a_refresh == a.A_REFRESH
        assert lay.a_freeze == a.A_FREEZE and lay.a_upgrade == a.A_UPGRADE
        assert lay.a_hero_power == a.A_HERO_POWER
        assert lay.a_dark_gift == a.A_DARK_GIFT and lay.a_cancel == a.A_CANCEL
        assert lay.a_buy == a.A_BUY and lay.a_sell == a.A_SELL
        assert lay.a_activate == a.A_ACTIVATE and lay.a_choose == a.A_CHOOSE
        assert lay.a_play == a.A_PLAY and lay.a_magnetize == a.A_MAGNETIZE
        assert lay.a_move == a.A_MOVE
        assert lay.n_shop == a.N_SHOP and lay.n_board == a.N_BOARD
        assert lay.n_hand == a.N_HAND and lay.n_choice == a.N_CHOICE
        assert lay.n_pos == a.N_POS and lay.n_powers == a.N_POWERS


# ══════════════════════════════════════════════════════════════════════
# 5. 真实环境候选转换（legacy BattlegroundsEnv → 标准动作）
# ══════════════════════════════════════════════════════════════════════


class TestRealEnvConversion:
    def test_real_env_candidates_convert_roundtrip(self):
        """真实对局候选：全部可转标准动作；仅"目标被折叠"的项有损。"""
        import random as _random  # noqa: PLC0415

        from hsbg.env import BattlegroundsEnv  # noqa: PLC0415

        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=0)
        try:
            obs = env.reset(seed=0)
            rng = _random.Random(0)
            seen_kinds = set()
            checked = 0
            lossy = 0
            for _ in range(60):
                if not obs.candidates:
                    break
                for cand in obs.candidates:
                    std = a.candidate_to_std(cand, obs)
                    assert std is not None, cand
                    back = a.std_to_candidate(std, obs)
                    assert back is not None, (cand, std)
                    seen_kinds.add(cand.kind)
                    checked += 1
                    magnetize = (cand.kind == "play_minion"
                                 and cand.tgt_zone == "board"
                                 and cand.position < 0)
                    if cand.tgt_zone and not magnetize:
                        # 目标被折叠进 Play/技能 → 反向无目标（documented）
                        lossy += 1
                    elif (cand.kind == "play_minion" and not magnetize
                          and cand.position < 0):
                        # legacy 的 position=-1 = "追加到最右"；标准 Play.pos
                        # 是显式位置（pos == 场上随从数 = 追加），语义等价、
                        # 签名不同（documented）
                        assert back.kind == "play_minion"
                        assert back.src_slot == cand.src_slot
                        assert back.position == len(obs.board), (
                            back, len(obs.board))
                    else:
                        assert back.signature() == cand.signature(), (
                            cand, std, back)
                obs = env.step(rng.randrange(len(obs.candidates)))[0]
            # 覆盖多数动作类型 + 足量样本
            assert checked > 100, checked
            assert len(seen_kinds) >= 6, seen_kinds
            assert lossy >= 0
        finally:
            env.close()
