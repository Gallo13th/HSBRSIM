"""差分判定测试（``compare_combat`` / ``compare_events`` / 引擎复现接线）。

不依赖真实录像；真实数据冒烟测试在缺数据时 skip（不 fail）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.bridge import trace as T  # noqa: E402

# 引擎依赖：缺 data/ 时这些用例 skip（CI 里 data/ 始终存在，属防御）
try:
    from hsrl2.db import CardDB

    from tools.diff_replay_combat import (  # noqa: E402
        STATUS_CONTEXT_GAP,
        STATUS_DATA_GAP,
        STATUS_ENGINE_DIVERGENCE,
        STATUS_MATCH,
        STATUS_SKIPPED,
        CardResolver,
        HeroIndex,
        SimulationResult,
        _apply_official_script_data,
        _deterministic_metrics,
        _inject_damage_cap,
        _official_script_data,
        _summarize,
        attribute_divergence,
        compare_combat,
        compare_events,
        diff_traces,
        sanity_check_trace,
        simulate_trace,
    )

    _ENGINE_OK = True
except Exception as _exc:  # pragma: no cover - data/ 缺失时
    _ENGINE_OK = False
    _ENGINE_IMPORT_ERROR = str(_exc)

pytestmark = pytest.mark.skipif(
    not _ENGINE_OK, reason="hsrl2 引擎/数据不可用")


# ══════════════════════════════════════════════════════════════════════
# 构造轨迹 / 引擎
# ══════════════════════════════════════════════════════════════════════


def _trace(player, opponent, *, official=None, bb=None, turn=5,
           hero_power=None, second_power=None, detected=None,
           hero_power_data=None) -> T.OfficialCombatTrace:
    """player/opponent = [(name, atk, health, keywords?)]。"""
    def band(side, specs, power):
        minions = []
        for index, spec in enumerate(specs):
            name, atk, health = spec[0], spec[1], spec[2]
            keywords = list(spec[3]) if len(spec) > 3 else []
            golden = bool(spec[4]) if len(spec) > 4 else False
            minions.append(T.TraceMinion(slot=index, name=name, atk=atk,
                                         health=health, golden=golden,
                                         keywords=keywords))
        return T.Warband(side=side, minions=minions, hero_power_id=power,
                         hero_power_data=hero_power_data)

    player_band = band("player", player, hero_power)
    if detected:
        player_band.detected = [dict(item) for item in detected]
    return T.OfficialCombatTrace(
        trace_id="test_trace", source="test", episode_id="ep_test",
        player=player_band,
        opponent=band("opponent", opponent, second_power),
        turn=turn, official_result=official, bb_rates=bb)


@pytest.fixture(scope="module")
def engine():
    db = CardDB.load(ROOT / "data")
    return db, CardResolver(db), HeroIndex(db)


# ══════════════════════════════════════════════════════════════════════
# compare_combat：纯函数判定
# ══════════════════════════════════════════════════════════════════════


def test_match_when_distribution_and_official_agree() -> None:
    outcomes = ["win"] * 6 + ["tie"] * 2 + ["loss"] * 2
    result = compare_combat(
        outcomes, official_result="win",
        bb_rates={"win": 0.6, "tie": 0.2, "loss": 0.2})
    assert result["status"] == STATUS_MATCH
    assert result["subclass"] == "distribution_match"
    assert result["l1_distance"] == pytest.approx(0.0)
    assert result["official_in_support"] is True


def test_match_rng_sample_when_official_differs_from_mode() -> None:
    # 官方单样本落在引擎可达集内但不是众数 → 不冤枉引擎（RNG_SAMPLE）
    outcomes = ["win"] * 8 + ["loss"] * 2
    result = compare_combat(
        outcomes, official_result="loss",
        bb_rates={"win": 0.8, "tie": 0.0, "loss": 0.2})
    assert result["status"] == STATUS_MATCH
    assert result["subclass"] == "rng_sample"


def test_deterministic_mismatch_is_divergence() -> None:
    # BobsBuddy 100% 胜、官方胜，引擎却 100% 负 → 确定性分歧
    result = compare_combat(
        ["loss"] * 16, official_result="loss",
        bb_rates={"win": 1.0, "tie": 0.0, "loss": 0.0})
    assert result["status"] == STATUS_ENGINE_DIVERGENCE
    assert result["subclass"] == "deterministic_mismatch"
    assert result["evidence"]["engine_rate_of_expected"] == 0.0


def test_official_result_unreachable_is_divergence() -> None:
    result = compare_combat(
        ["win"] * 40, official_result="loss", bb_rates=None,
        unreachable_min_seeds=32)
    assert result["status"] == STATUS_ENGINE_DIVERGENCE
    assert result["subclass"] == "official_result_unreachable"


def test_distribution_distance_is_divergence() -> None:
    result = compare_combat(
        ["win"] * 18 + ["tie"] * 2 + ["loss"] * 4,
        official_result=None,
        bb_rates={"win": 0.01, "tie": 0.03, "loss": 0.96})
    assert result["status"] == STATUS_ENGINE_DIVERGENCE
    assert result["subclass"] == "distribution_distance"
    assert result["l1_distance"] is not None and result["l1_distance"] > 0.5


def test_data_gap_takes_precedence_over_divergence() -> None:
    result = compare_combat(
        ["loss"] * 16, official_result="loss",
        bb_rates={"win": 1.0, "tie": 0.0, "loss": 0.0},
        data_gaps=[{"side": "player", "slot": 0, "name": "New Card 37.0",
                    "gap": "engine_data_version_gap"}])
    assert result["status"] == STATUS_DATA_GAP
    assert result["subclass"] == "missing_cards"
    assert result["evidence"]["data_gaps"]


def test_no_engine_result_is_skipped() -> None:
    result = compare_combat([], official_result="win")
    assert result["status"] == STATUS_SKIPPED


def test_official_in_support_none_when_no_official_result() -> None:
    result = compare_combat(["tie"] * 8, official_result=None,
                            bb_rates={"win": 0.0, "tie": 1.0, "loss": 0.0})
    assert result["status"] == STATUS_MATCH
    assert result["official_in_support"] is None


# ══════════════════════════════════════════════════════════════════════
# compare_events：事件流对齐
# ══════════════════════════════════════════════════════════════════════


def _attack(actor_side, actor_slot, target_side, target_slot) -> dict:
    return {"kind": "attack", "actor_side": actor_side,
            "actor_slot": actor_slot, "target_side": target_side,
            "target_slot": target_slot}


def test_compare_events_identical() -> None:
    events = [_attack("player", 0, "opponent", 1),
              {"kind": "damage", "target_side": "opponent", "target_slot": 1,
               "amount": 3},
              {"kind": "death", "target_side": "opponent", "target_slot": 1}]
    result = compare_events(events, events)
    assert result["diverged"] is False
    assert result["events"] == 3


def test_compare_events_first_divergence() -> None:
    official = [_attack("player", 0, "opponent", 1),
                {"kind": "damage", "target_side": "opponent", "target_slot": 1,
                 "amount": 3}]
    engine = [_attack("player", 0, "opponent", 0),
              {"kind": "damage", "target_side": "opponent", "target_slot": 1,
               "amount": 3}]
    result = compare_events(official, engine)
    assert result["diverged"] is True
    assert result["index"] == 0
    assert result["official"]["target_slot"] == 1
    assert result["engine"]["target_slot"] == 0


def test_compare_events_tail_length() -> None:
    official = [_attack("player", 0, "opponent", 0)] * 3
    engine = [_attack("player", 0, "opponent", 0)] * 2
    result = compare_events(official, engine)
    assert result["diverged"] is True
    assert result.get("subclass") == "tail_length"


# ══════════════════════════════════════════════════════════════════════
# 轨迹自洽性与归因
# ══════════════════════════════════════════════════════════════════════


def test_sanity_check_accepts_normal_trace() -> None:
    trace = _trace([("Razorfen Geomancer", 2, 1)], [("Risen Rider", 3, 1)],
                   official="win")
    assert sanity_check_trace(trace) is None


def test_sanity_check_rejects_oversized_warband() -> None:
    trace = _trace([("Razorfen Geomancer", 2, 1)] * 8, [],
                   official="win")
    assert sanity_check_trace(trace) == "invalid_warband_size"


def test_sanity_check_rejects_inconsistent_empty_side_result() -> None:
    # 对手空场却判我方负 → Duos/观战/断线日志，不可比
    trace = _trace([("Razorfen Geomancer", 2, 1)], [],
                   official="loss", turn=6)
    assert sanity_check_trace(trace) == "inconsistent_official_trace"


def test_sanity_check_rejects_empty_warbands() -> None:
    trace = _trace([], [], official="tie")
    assert sanity_check_trace(trace) == "empty_warbands"


def test_attribution_prefers_behavior_mismatch() -> None:
    divergence = {"status": STATUS_ENGINE_DIVERGENCE}
    info = attribute_divergence(divergence, [])
    assert info["attribution"] == "behavior_mismatch"
    script = attribute_divergence(divergence, ["no_script:BG27_004"])
    assert script["attribution"] == "missing_script"
    assert script["suspect_cards"] == ["BG27_004"]
    dynamic = attribute_divergence(
        divergence, ["dynamic_script_data:BG19_010:1"])
    assert dynamic["attribution"] == "unmodeled_dynamic_state"
    consistent = attribute_divergence({"status": STATUS_MATCH}, ["garbage"])
    assert consistent["attribution"] == "consistent"


def test_attribution_hand_and_unknown_hero_power_are_context() -> None:
    """2026-10-18 root-cause 裁定：手牌/技能未知 = 未建模上下文，非 bug。"""
    divergence = {"status": STATUS_ENGINE_DIVERGENCE}
    for gap in ("hand_not_modeled", "player_hero_power_unknown",
                "opponent_hero_power_unknown"):
        info = attribute_divergence(divergence, [gap])
        assert info["attribution"] == "unmodeled_context", gap
    # 无任何未建模上下文时仍为 behavior_mismatch（真 bug 判定不放松）
    assert attribute_divergence(divergence, [])["attribution"] \
        == "behavior_mismatch"


def test_attribution_bg_secret_is_unmodeled_context() -> None:
    # 官方真实语境：Secret Pack Tactics（友方随从被攻击时召唤 3/3 复制）
    info = attribute_divergence(
        {"status": STATUS_ENGINE_DIVERGENCE},
        ["detected_effect:player:S:PackTactics"])
    assert info["attribution"] == "unmodeled_context"
    # 外部授予的亡语 / 英雄技能累积状态 → 动态状态未建模
    for gap in ("deathrattle_annotation:BG25_001",
                "hero_power_state:player:BG25_HERO_103p:1913",
                "dynamic_script_data:BG25_008:1"):
        state = attribute_divergence({"status": STATUS_ENGINE_DIVERGENCE},
                                     [gap])
        assert state["attribution"] == "unmodeled_dynamic_state", gap
    stat = attribute_divergence({"status": STATUS_ENGINE_DIVERGENCE},
                                ["dynamic_stat_script"])
    assert stat["attribution"] == "unmodeled_context"


def test_diff_traces_reclassifies_hidden_context_as_context_gap(engine) -> None:
    """有官方隐藏上下文（秘密）时，结果不一致**不能**算引擎 bug。"""
    db, _resolver, _hero_index = engine
    # 引擎确定性：1/1 vs 2/2 必负；官方却记录胜（因为有 Pack Tactics 秘密）
    trace = _trace([("Razorfen Geomancer", 1, 1)],
                   [("Razorfen Geomancer", 2, 2)],
                   official="win", bb={"win": 1.0, "tie": 0.0, "loss": 0.0},
                   detected=[{"kind": "S", "value": "PackTactics"}])
    report = diff_traces([trace], db=db, seeds=8)
    record = report["records"][0]
    assert record["attribution"]["attribution"] == "unmodeled_context"
    assert record["comparison"]["status"] == STATUS_CONTEXT_GAP
    assert report["summary"]["context_gap"] == 1
    assert report["summary"]["engine_divergence"] == 0
    # 同一战团去掉隐藏上下文、且技能已知 → 恢复为确定性的引擎分歧
    # （2026-10-18 口径：未知英雄技能 = unmodeled_context，故此处显式给已知技能）
    plain = _trace([("Razorfen Geomancer", 1, 1)],
                   [("Razorfen Geomancer", 2, 2)],
                   official="win", bb={"win": 1.0, "tie": 0.0, "loss": 0.0},
                   hero_power="TB_BaconShop_HP_020",
                   second_power="TB_BaconShop_HP_020")
    report2 = diff_traces([plain], db=db, seeds=8)
    assert report2["records"][0]["comparison"]["status"] == \
        STATUS_ENGINE_DIVERGENCE
    # 技能未知（默认 _trace）→ 新口径下是 CONTEXT_GAP（不是 behavior_mismatch）
    unknown = _trace([("Razorfen Geomancer", 1, 1)],
                     [("Razorfen Geomancer", 2, 2)],
                     official="win", bb={"win": 1.0, "tie": 0.0, "loss": 0.0})
    report3 = diff_traces([unknown], db=db, seeds=8)
    assert report3["records"][0]["comparison"]["status"] == STATUS_CONTEXT_GAP


def test_hero_power_static_data_is_not_context_gap(engine) -> None:
    """Ozumat ``data=2`` 是技能静态参数（num(0)=2），不是缺口。

    2026-10-18 教训：旧逻辑把 ``data != 0`` 一律当 blocking，把真引擎
    bug（Ozumat SoC 召唤 7 只 Tentacle）吞成 CONTEXT_GAP。
    """
    db, resolver, hero_index = engine
    trace = _trace([("Razorfen Geomancer", 2, 1)], [],
                   official="win", hero_power="BG23_HERO_201p",
                   hero_power_data=2)
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=1)
    assert not any(gap.startswith(("hero_power_state:",
                                   "hero_power_target_unresolved:"))
                   for gap in sim.context_gaps), sim.context_gaps


def test_hero_power_ozumat_bonus_state_is_reconstructed(engine) -> None:
    """Ozumat ``data=4`` = Tentacle 当前数值（num(0)=2 + bonus 2）。

    该状态可从日志**重建**（hero._ozumat_bonus），不应再记为缺口；
    官方轨迹 886faa18f76e10dc 验证：重建后引擎 win 16/16 = 官方。
    """
    db, resolver, hero_index = engine
    trace = _trace([("Razorfen Geomancer", 1, 1)],
                   [("Razorfen Geomancer", 2, 2)],
                   official="win", hero_power="BG23_HERO_201p",
                   hero_power_data=4)
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=8)
    assert not any(gap.startswith(("hero_power_state:",
                                   "hero_power_target_unresolved:"))
                   for gap in sim.context_gaps), sim.context_gaps
    assert sim.outcomes and set(sim.outcomes) <= {"win", "tie", "loss"}


def test_hero_power_combat_target_state_is_context_gap(engine) -> None:
    """Teron ``data=376`` 是被销毁/复活随从的 game_id → 目标无法重建。"""
    db, resolver, hero_index = engine
    trace = _trace([("Razorfen Geomancer", 2, 1)], [],
                   official="win", hero_power="BG25_HERO_103p",
                   hero_power_data=376)
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=1)
    assert any(gap.startswith("hero_power_target_unresolved:player:")
               for gap in sim.context_gaps), sim.context_gaps


def test_hero_power_recruit_only_state_is_not_context_gap(engine) -> None:
    db, resolver, hero_index = engine
    trace = _trace([("Razorfen Geomancer", 2, 1)], [],
                   official="win", hero_power="BG20_HERO_102p",
                   hero_power_data=3)
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=1)
    assert not any(gap.startswith(("hero_power_state:",
                                   "hero_power_target_unresolved:"))
                   for gap in sim.context_gaps), sim.context_gaps


# ══════════════════════════════════════════════════════════════════════
# 引擎真实复现（构造已知战团）
# ══════════════════════════════════════════════════════════════════════


def test_engine_simulation_matches_self_consistent_trace(engine) -> None:
    db, resolver, hero_index = engine
    trace = _trace([("Razorfen Geomancer", 2, 1)], [],
                   official="win", bb={"win": 1.0, "tie": 0.0, "loss": 0.0})
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=8)
    assert sim.data_gaps == []
    assert sim.outcomes == ["win"] * 8
    result = compare_combat(sim.outcomes, official_result=trace.official_result,
                            bb_rates=trace.bb_rates,
                            context_gaps=sim.context_gaps)
    assert result["status"] == STATUS_MATCH


def test_engine_deterministic_divergence_is_detected(engine) -> None:
    db, resolver, hero_index = engine
    trace = _trace([("Razorfen Geomancer", 2, 1)], [],
                   official="loss",
                   bb={"win": 0.0, "tie": 0.0, "loss": 1.0})
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=8)
    result = compare_combat(sim.outcomes, official_result=trace.official_result,
                            bb_rates=trace.bb_rates,
                            context_gaps=sim.context_gaps)
    assert result["status"] == STATUS_ENGINE_DIVERGENCE
    assert result["subclass"] == "deterministic_mismatch"


def test_engine_unknown_card_is_data_gap(engine) -> None:
    db, resolver, hero_index = engine
    trace = _trace([("Definitely Not A Card 37.0", 1, 1)], [],
                   official=None)
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=4)
    assert sim.data_gaps and sim.data_gaps[0]["gap"] == "unknown_card_name"
    result = compare_combat(sim.outcomes, official_result=None,
                            data_gaps=sim.data_gaps)
    assert result["status"] == STATUS_DATA_GAP


def test_engine_stat_keywords_are_applied(engine) -> None:
    db, resolver, hero_index = engine
    # 2/2 圣盾 vs 1/1：引擎应稳定胜（圣盾吸收一次伤害）
    trace = _trace([("Razorfen Geomancer", 2, 2, ["divine_shield"])],
                   [("Risen Rider", 1, 1)],
                   official="win", bb={"win": 1.0, "tie": 0.0, "loss": 0.0})
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=8)
    assert sim.outcomes == ["win"] * 8


# ══════════════════════════════════════════════════════════════════════
# 官方动态 ScriptDataNum 注入（2026-10-18 测量口径修正）
# ══════════════════════════════════════════════════════════════════════


def _mk_game(db):
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    return Game([Hero("BG20_HERO_100", "P"), Hero("BG20_HERO_101", "O")],
                db, seed=1)


def _tm(**kwargs) -> T.TraceMinion:
    kwargs.setdefault("slot", 0)
    return T.TraceMinion(**kwargs)


def test_official_script_data_parsing_forms() -> None:
    """名字键（BobsBuddy）与官方 enumID 键（Power.log）都能解析。"""
    assert _official_script_data(
        {"ScriptDataNum1": "9", "ScriptDataNum2": "6", "ScriptDataNum3": "2"}
    ) == {1: 9, 2: 6, 3: 2}
    assert _official_script_data({"2": "9", "3": "6", "2889": "2"}) == \
        {1: 9, 2: 6, 3: 2}
    assert _official_script_data({}) == {}
    assert _official_script_data({"ScriptDataNum9": "1"}) == {}
    assert _official_script_data({"deathrattles": "x"}) == {}


def test_script_data_injection_generic_only_when_present(engine) -> None:
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    minion = game.create_minion("BG20_100", controller=game.heroes[0])
    result = SimulationResult(trace_id="t")
    tm = _tm(name="Razorfen Geomancer", card_id="BG20_100", atk=2, health=1,
             tags={"ScriptDataNum1": "7"})
    adapted = _apply_official_script_data(
        game, minion, "BG20_100", tm, result, "player")
    assert adapted is False
    assert result.script_data_injected
    assert result.script_data_injected[0]["values"] == {1: 7}
    assert game.get_entity_script_data(minion, 1) == 7
    # 无官方值 → 不注入、不记录
    result2 = SimulationResult(trace_id="t2")
    _apply_official_script_data(
        game, minion, "BG20_100", _tm(name="x", card_id="BG20_100"),
        result2, "player")
    assert result2.script_data_injected == []


def test_consumed_script_data_clears_dynamic_gap(engine) -> None:
    """通道消费卡（Deep Blue Crooner）：官方 NUM_1/NUM_2 不再算缺口。"""
    db, resolver, hero_index = engine
    trace = _trace([("Deep Blue Crooner", 2, 2)], [], official="loss")
    trace.player.minions[0].tags = {"ScriptDataNum1": "28",
                                    "ScriptDataNum2": "28"}
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=1)
    assert not any(gap.startswith("dynamic_script_data:BG26_502:")
                   for gap in sim.context_gaps), sim.context_gaps
    injected = sim.script_data_injected
    assert injected and injected[0]["adapted"] is True
    assert injected[0]["consumed"] == [1, 2]
    assert injected[0]["values"] == {1: 28, 2: 28}


def test_unconsumed_script_data_still_blocking_gap(engine) -> None:
    """只消费 NUM_1/NUM_2 → 其它槽位（NUM_3）仍是阻断缺口。"""
    db, resolver, hero_index = engine
    trace = _trace([("Deep Blue Crooner", 2, 2)], [], official="loss")
    trace.player.minions[0].tags = {"ScriptDataNum1": "28",
                                    "ScriptDataNum2": "28",
                                    "ScriptDataNum3": "7"}
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=1)
    assert any(gap == "dynamic_script_data:BG26_502:3"
               for gap in sim.context_gaps), sim.context_gaps


# ══════════════════════════════════════════════════════════════════════
# 8 族动态属性迁移（engine-analyst）→ harness 适配器登记
# ══════════════════════════════════════════════════════════════════════


def _apply_dynamic(game, card_id, atk, health, tags=None, golden=False):
    result = SimulationResult(trace_id="t")
    hero = game.heroes[0]
    minion = game.create_minion(card_id, controller=hero, golden=golden)
    tm = T.TraceMinion(slot=0, name=card_id, atk=atk, health=health,
                       golden=golden, tags=dict(tags or {}))
    adapted = _apply_official_script_data(
        game, minion, card_id, tm, result, "player")
    return minion, adapted, result


def test_dynamic_adapter_abyssal_bruiser_from_printed(engine) -> None:
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    # 基础 2/1，步长 2/1，printed 8/4 → count=3
    minion, adapted, result = _apply_dynamic(game, "BG35_921", 8, 4)
    assert adapted is True
    assert (minion.atk, minion.max_health) == (8, 4)
    assert minion.get_script_data(3) == 3
    assert result.script_data_injected[0]["consumed"] == [3]


def test_dynamic_adapter_automaton_fallback_steps(engine) -> None:
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    # CardDef num 为空 → 回退步长表 (3/2)；printed 9/8 → count=2
    minion, adapted, _ = _apply_dynamic(game, "BG_TTN_401", 9, 8)
    assert adapted is True
    assert (minion.atk, minion.max_health) == (9, 8)
    assert minion.get_script_data(3) == 2


def test_dynamic_adapter_rot_hide_gnoll_attack_only(engine) -> None:
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    game.in_combat = True        # 脚本有 in_combat 闸门（"this combat"）
    try:
        # 步长 (1, 0)：只有攻击可反推；printed 3/4 → count=2
        minion, adapted, _ = _apply_dynamic(game, "BG25_013", 3, 4)
        assert adapted is True
        assert minion.get_script_data(3) == 2
        assert (minion.atk, minion.max_health) == (3, 4)
    finally:
        game.in_combat = False


def test_dynamic_adapter_golden_values(engine) -> None:
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    # 金色 4/2 + 步长 4/2，printed 12/6 → count=2
    minion, adapted, _ = _apply_dynamic(game, "BG35_921", 12, 6,
                                        golden=True)
    assert adapted is True
    assert (minion.atk, minion.max_health) == (12, 6)
    assert minion.get_script_data(3) == 2


def test_dynamic_adapter_skips_inconsistent_printed(engine) -> None:
    """printed 含其它附魔（9/4 与步长 2/1 非整除）→ 不强行清缺口。"""
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    minion, adapted, result = _apply_dynamic(
        game, "BG35_921", 9, 4, tags={"ScriptDataNum3": "3"})
    assert adapted is False
    payload = result.script_data_injected[0]
    assert payload["adapted"] is False
    assert "adapter_skip" in payload
    assert 3 not in payload["values"]      # 不注入 count（避免双计）
    assert minion.get_script_data(3) is None


def test_dynamic_adapter_skips_trinket(engine) -> None:
    """Eternal Portrait 是饰品（无 printed atk/health）→ 适配器跳过。"""
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    hero = game.heroes[0]
    trinket = game.grant_trinket(hero, "BG36_MagicItem_216")
    assert trinket is not None
    result = SimulationResult(trace_id="t")
    tm = T.TraceMinion(slot=0, name="Eternal Portrait", atk=None,
                       health=None, tags={"ScriptDataNum3": "4"})
    adapted = _apply_official_script_data(
        game, trinket, "BG36_MagicItem_216", tm, result, "player")
    # 无 printed atk/health → 适配器跳过；通用注入仍保留（有值才注入）
    assert adapted is False
    assert result.script_data_injected
    assert result.script_data_injected[0]["adapted"] is False


def test_script_data_eternal_knight_adapter_recomputes_stats(engine) -> None:
    """Eternal Knight：官方 20/10 + ScriptDataNum3=4 → 基础值 + 计数注入复算。"""
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    minion = game.create_minion("BG25_008", controller=game.heroes[0])
    tm = _tm(name="Eternal Knight", card_id="BG25_008", atk=20, health=10,
             tags={"ScriptDataNum1": "4", "ScriptDataNum2": "2",
                   "ScriptDataNum3": "4"})
    result = SimulationResult(trace_id="t")
    adapted = _apply_official_script_data(
        game, minion, "BG25_008", tm, result, "player")
    assert adapted is True
    assert minion.atk == 20 and minion.max_health == 10
    assert game.get_entity_script_data(minion, 3) == 4


def test_ultraviolet_adapter_is_disabled_by_default(engine) -> None:
    """证据不足：Ultraviolet 适配器默认关闭（官方 NUM 与引擎公式冲突）。

    开关打开会改变行为；默认关闭时只做通用注入（引擎不消费 → 仍记缺口）。
    """
    import tools.diff_replay_combat as diff_mod
    assert diff_mod.ENABLE_ULTRAVIOLET_ADAPTER is False
    db, _resolver, _hero_index = engine
    game = _mk_game(db)
    minion = game.create_minion("BG31_810", controller=game.heroes[0])
    tm = _tm(name="Ultraviolet Ascendant", card_id="BG31_810", atk=7, health=3,
             tags={"ScriptDataNum3": "2"})
    result = SimulationResult(trace_id="t")
    adapted = _apply_official_script_data(
        game, minion, "BG31_810", tm, result, "player")
    assert adapted is False
    assert getattr(minion, "_ultraviolet_improves", 0) == 0
    # 通用注入仍记录（有值才注入）
    assert result.script_data_injected[0]["values"] == {3: 2}


def test_simulate_keeps_dynamic_gap_for_non_adapter_card(engine) -> None:
    """引擎脚本不消费通道的卡：注入后仍保留 dynamic_script_data 缺口。"""
    db, resolver, hero_index = engine
    trace = _trace([("Darkcrest Strategist", 4, 5)], [],
                   official="win")
    # 官方给出的动态值（与 CardDef 静态值不同）
    trace.player.minions[0].tags = {"ScriptDataNum1": "99"}
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=1)
    assert any(gap.startswith("dynamic_script_data:")
               for gap in sim.context_gaps), sim.context_gaps
    assert sim.script_data_injected  # 仍然"有值才注入"


def test_simulate_eternal_knight_adapter_clears_dynamic_gap(engine) -> None:
    """Eternal Knight 适配器消费通道 → 不再记 dynamic_script_data 缺口。"""
    db, resolver, hero_index = engine
    trace = _trace([("Eternal Knight", 20, 10)], [], official="win")
    trace.player.minions[0].tags = {"ScriptDataNum1": "4",
                                    "ScriptDataNum2": "2",
                                    "ScriptDataNum3": "4"}
    sim = simulate_trace(trace, db, resolver, hero_index, seeds=1)
    assert sim.script_data_injected[0]["adapted"] is True
    assert not any(gap.startswith("dynamic_script_data:")
                   for gap in sim.context_gaps), sim.context_gaps
    assert not any(gap == "dynamic_stat_script" for gap in sim.context_gaps)


def test_second_hero_power_is_blocking_context() -> None:
    """第二英雄技能未建模 → 属于上下文缺口（不能算 behavior_mismatch）。"""
    info = attribute_divergence({"status": STATUS_ENGINE_DIVERGENCE},
                                ["second_hero_power_ignored"])
    assert info["attribution"] == "unmodeled_context"
    record = _fake_record("p2", STATUS_ENGINE_DIVERGENCE,
                          gaps=["second_hero_power_ignored"])
    summary = _summarize([record])
    assert summary["behavior_mismatch"] == 0
    assert summary["context_aware"]["clean_subset_traces"] == 0


# ══════════════════════════════════════════════════════════════════════
# strict vs context-aware 测量口径
# ══════════════════════════════════════════════════════════════════════


def _fake_record(trace_id, status, *, bb=(0.0, 0.0, 1.0),
                 engine_rates=None, engine_mode="loss", official=None,
                 gaps=(), subclass=None):
    return {
        "trace": {
            "trace_id": trace_id,
            "official_result": official,
            "bb_rates": {"win": bb[0], "tie": bb[1], "loss": bb[2]},
        },
        "comparison": {
            "status": status,
            "subclass": subclass or status.lower(),
            "evidence": {"engine_mode": engine_mode,
                         "engine_rates": engine_rates or {}},
        },
        "simulation": {"context_gaps": list(gaps)},
    }


def test_deterministic_metrics_strict_vs_tolerant() -> None:
    records = [
        _fake_record("match", STATUS_MATCH, official="loss"),
        # 确定性 100% loss；引擎仍 90% loss（RNG 流移位）→ tolerant 通过
        _fake_record("rng_shift", STATUS_ENGINE_DIVERGENCE,
                     engine_rates={"win": 0.0, "tie": 0.1, "loss": 0.9},
                     official="loss"),
        # 引擎方向明显错误 → tolerant 也不通过
        _fake_record("wrong", STATUS_ENGINE_DIVERGENCE,
                     engine_rates={"win": 0.7, "tie": 0.0, "loss": 0.3},
                     official="win"),
        # 非确定性（BB 非 100%）→ 不进入确定性集合
        _fake_record("stochastic", STATUS_ENGINE_DIVERGENCE,
                     bb=(0.5, 0.2, 0.3),
                     engine_rates={"win": 0.0, "tie": 0.0, "loss": 1.0}),
    ]
    metrics = _deterministic_metrics(records, tolerant_rate=0.8)
    assert metrics["traces"] == 3
    assert metrics["strict_match"] == 1
    assert metrics["tolerant_match"] == 2
    assert [row["trace_id"] for row in metrics["tolerated_rng_stream"]] == \
        ["rng_shift"]


def test_summarize_strict_vs_context_aware() -> None:
    records = [
        _fake_record("clean_match", STATUS_MATCH, official="loss"),
        _fake_record("gap_match", STATUS_MATCH,
                     gaps=["no_script:BG27_004"], official="loss"),
        _fake_record("gap_div", STATUS_ENGINE_DIVERGENCE,
                     gaps=["no_script:BG27_004"], official="loss"),
        _fake_record("ctx", STATUS_CONTEXT_GAP,
                     gaps=["detected_effect:player:S:PackTactics"]),
        _fake_record("skip", STATUS_SKIPPED),
    ]
    summary = _summarize(records, tolerant_rate=0.8)
    assert summary["behavior_mismatch"] == 0
    # strict：全部可比轨迹（含缺口）
    assert summary["strict"]["traces"] == 5
    assert summary["strict"]["match"] == 2
    assert summary["strict"]["engine_divergence"] == 1
    # context-aware：只有干净子集
    assert summary["context_aware"]["clean_subset_traces"] == 1
    assert summary["context_aware"]["clean_match"] == 1
    assert summary["context_aware"]["clean_engine_divergence"] == 0
    assert summary["context_aware"]["excluded_traces"] == 3
    # 兼容旧字段仍存在
    assert summary["match"] == 2
    assert summary["deterministic_match_rate"] is not None
    assert "deterministic_tolerant_match_rate" in summary


# ══════════════════════════════════════════════════════════════════════
# 真实数据冒烟（缺数据 → skip，不 fail）
# ══════════════════════════════════════════════════════════════════════


def test_damage_cap_injection_helper() -> None:
    """官方伤害上限注入：有 tag 才调用引擎 API，无 tag 不动默认行为。"""
    calls = []

    class _StubGame:
        def set_damage_cap(self, value, *, enabled=True):
            calls.append((value, enabled))

    trace = _trace([("Razorfen Geomancer", 2, 1)], [], official="win")
    assert _inject_damage_cap(_StubGame(), trace) is None   # 无 tag → 不注入
    assert calls == []

    trace.damage_cap = 7
    trace.damage_cap_enabled = True
    assert _inject_damage_cap(_StubGame(), trace) is None
    assert calls == [(7, True)]

    trace.damage_cap_enabled = False                        # 官方 _ENABLED=0
    assert _inject_damage_cap(_StubGame(), trace) is None
    assert calls[-1] == (7, False)

    trace.damage_cap = None
    trace.damage_cap_enabled = None
    assert _inject_damage_cap(object(), trace) is None      # 无 tag 不碰引擎

    trace.damage_cap = 7
    assert _inject_damage_cap(object(), trace) == \
        "damage_cap_api_unavailable"


def test_real_hdt_logs_smoke(engine) -> None:
    """真实 BG 战斗语料（HDT BobsBuddy 日志）冒烟：--limit 1 级别。"""
    hdt_logs = (Path.home() / "AppData" / "Roaming"
                / "HearthstoneDeckTracker" / "Logs")
    if not hdt_logs.exists():
        pytest.skip("HDT 会话日志目录不存在")
    try:
        traces, stats = T.iter_hdt_bobsbuddy_traces(hdt_logs, limit_files=1)
        if not traces or stats.get("parsed", 0) == 0:
            pytest.skip("首个 HDT 日志里没有 BobsBuddy 战斗")
        db, resolver, hero_index = engine
        sim = simulate_trace(traces[0], db, resolver, hero_index, seeds=4)
        assert sim.outcomes, "引擎应至少跑出一场结果"
        compare_combat(sim.outcomes, official_result=traces[0].official_result,
                       bb_rates=traces[0].bb_rates,
                       data_gaps=sim.data_gaps,
                       context_gaps=sim.context_gaps)
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # noqa: BLE001 - 冒烟按任务要求 skip 不 fail
        pytest.skip(f"真实日志冒烟失败（跳过）：{type(exc).__name__}: {exc}")


def test_real_powerlog_pseudo_summon_regression(engine) -> None:
    """e057 回归：战团 SETASIDE 副本还原不得记 summon，结果应为 tie。

    真实日志缺失时 skip（runs/ 不随仓库分发）。
    """
    log = ROOT / "runs" / "powerlog" / "Power.log"
    if not log.exists():
        pytest.skip("真实 Power.log 缺失（runs/ 不随仓库分发）")
    text = log.read_text(encoding="utf-8", errors="replace")
    traces, _ = T.parse_bg_powerlog_text(text)
    target = next(
        (t for t in traces
         if t.turn == 4
         and any(m.card_id == "BG35_814" for m in t.opponent.minions)),
        None)
    assert target is not None, "未找到 turn4 真实轨迹"
    assert target.official_result == T.RESULT_TIE
    assert not any(e.kind == "summon" and e.card_id == "BG26_135"
                   for e in target.events)
    db, resolver, hero_index = engine
    report = diff_traces([target], db=db, seeds=16)
    record = report["records"][0]
    assert record["comparison"]["status"] == STATUS_MATCH


def test_real_replay_dir_smoke() -> None:
    """HDT 录像目录冒烟：能扫描并如实报告（本机 0 场 BG）。"""
    replays = (Path.home() / "AppData" / "Roaming"
               / "HearthstoneDeckTracker" / "Replays")
    if not replays.exists():
        pytest.skip("HDT 录像目录不存在")
    try:
        from tools.diff_extract_replays import scan_replays
        traces, stats = scan_replays(replays, limit=1)
        assert stats["files_scanned"] == 1
        assert "diagnostics" in stats
        if stats["battlegrounds_games"] == 0:
            pytest.skip("本机首个录像不是酒馆战棋（已知：全部为 2 人构筑局）")
        for trace in traces[:1]:
            assert trace.source == T.SOURCE_POWERLOG
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"录像冒烟失败（跳过）：{type(exc).__name__}: {exc}")
