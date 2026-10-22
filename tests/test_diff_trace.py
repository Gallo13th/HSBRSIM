"""``official_combat_trace.v1`` 抽取/序列化测试（不依赖真实录像）。

数据源格式来自本机真实日志（``tests/fixtures`` 级别的合成片段）：
* HDT BobsBuddy 会话日志（真实 BG 战斗语料，见 docs/DIFF_HARNESS.md）；
* Power.log BG 格式（本机暂无真实 BG 日志，用合成片段覆盖解析路径）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.bridge import trace as T  # noqa: E402

# ══════════════════════════════════════════════════════════════════════
# 合成 HDT BobsBuddy 会话日志（格式逐行对齐真实日志）
# ══════════════════════════════════════════════════════════════════════

BOBSBUDDY_LOG = "\n".join([
    "9:03:00 PM|Info|GameV2.CurrentMode >> BACON",
    "21:04:46|Info|GameEventHandler.HandleGameStart >> --- Game start ---",
    "21:04:46|Info|BobsBuddyInvoker.State >> New State: Shopping",
    "21:06:12|Info|GameEventHandler.HandleTurnStart >> --- Player turn 1 ---",
    "21:06:12|Info|BobsBuddyInvoker.StartCombat >> coin_1",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> ----- Simulation Input -----",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> Player: heroPower=BG22_HERO_201p,"
    " used=False, data=0",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> Player: extraHeroPower="
    "BG34_HERO_000p, used=False, data=7",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> Hand: [Bream Counter 12/12,"
    " ScriptDataNum1=6, ScriptDataNum2=6]",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> [Goldrinn, the Great Wolf 8/8,"
    " ScriptDataNum1=8]",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> [Risen Rider 3/1, Taunt, Reborn]",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> [Monstrous Macaw 11/9, G, Div]",
    "21:06:12|Info|... 1 duplicate messages",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> ---",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> Opponent: heroPower="
    "TB_BaconShop_HP_044, used=True, data=2",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> Hand: SpellCardEntity,"
    " [Tide Oracle Morgl 3/12, Poison]",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> [BG24_Quest_124 (4/10):"
    " BG24_HERO_100_Buddyt]",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> [Gluttonous Trogg 13/16,"
    " ScriptDataNum2=4]",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> ---",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> Detected the following"
    " player S.",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> PackTactics",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> ----- End of Input -----",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> Running simulations with"
    " MaxIterations=10000 and ThreadCount=6...",
    "21:06:12|Info|BobsBuddyInvoker.RunSimulation >> ----- Simulation Output -----",
    "21:06:13|Info|BobsBuddyInvoker.RunSimulation >> Duration=98.4ms,"
    " ExitCondition=CompletedSimulations, Iterations=9996",
    "21:06:13|Info|BobsBuddyInvoker.RunSimulation >> WinRate=71.7% (Lethal=0%),"
    " TieRate=25.3%, LossRate=3% (Lethal=0%)",
    "21:06:13|Info|BobsBuddyInvoker.RunSimulation >> ----- End of Output -----",
    "21:06:13|Info|BobsBuddyInvoker.RunAndDisplaySimulationAsync >>"
    " Displaying simulation results",
    "21:06:14|Info|BobsBuddyInvoker.UpdateAttackingEntities >> Updating entities"
    " with attacker=Elise Starseeker, defender=Ambassador Faelin",
    "21:06:19|Info|GameEventHandler.HandleTurnStart >> --- Player turn 2 ---",
    "21:06:19|Info|BobsBuddyInvoker.StartShoppingAsync >> coin_1",
    "21:06:19|Info|BobsBuddyInvoker.ValidateSimulationResultAsync >>"
    " Validating results...",
    "21:06:19|Info|BobsBuddyInvoker.ValidateSimulationResultAsync >> result=Win,"
    " lethalResult=NoOneDied",
    "21:06:19|Info|GameEventHandler.HandleTurnStart >> --- Opponent turn 2 ---",
    "21:06:59|Info|BobsBuddyInvoker.StartCombat >> coin_2",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> ----- Simulation Input -----",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> Player: heroPower=BG22_HERO_201p,"
    " used=False, data=0",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> Hand: ",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> [Very Hungry Winterfinner 2/5,"
    " Taunt]",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> ---",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> Opponent: heroPower="
    "BG35_HERO_001p, used=False, data=2",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> Hand: ",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> [Twilight Hatchling 1/1,"
    " ScriptDataNum1=3]",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> ---",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> ----- End of Input -----",
    "21:06:59|Info|BobsBuddyInvoker.RunSimulation >> ----- Simulation Output -----",
    "21:07:00|Info|BobsBuddyInvoker.RunSimulation >> Iterations=9996",
    "21:07:00|Info|BobsBuddyInvoker.RunSimulation >> WinRate=0% (Lethal=0%),"
    " TieRate=100%, LossRate=0% (Lethal=0%)",
    "21:07:00|Info|BobsBuddyInvoker.RunSimulation >> ----- End of Output -----",
    "21:07:07|Info|GameEventHandler.HandleTurnStart >> --- Player turn 3 ---",
    "21:07:07|Info|BobsBuddyInvoker.StartShoppingAsync >> coin_2",
    "21:07:07|Info|BobsBuddyInvoker.ValidateSimulationResultAsync >> result=Tie,"
    " lethalResult=NoOneDied",
    "这不是一行合法日志",
])


# ══════════════════════════════════════════════════════════════════════
# 合成 Power.log（酒馆战棋：8 人局 + BACON_IN_COMBAT_PHASE 战斗）
# ══════════════════════════════════════════════════════════════════════


def _tag_line(tag: str, value: str) -> str:
    return f"D 16:00:00.1000000 GameState.DebugPrintPower() -     tag={tag} value={value}"


def _build_bg_powerlog() -> str:
    lines = ["D 16:00:00.1000000 GameState.DebugPrintPower() - CREATE_GAME",
             "D 16:00:00.1000000 GameState.DebugPrintPower() - GameEntity EntityID=1",
             _tag_line("CARDTYPE", "GAME")]
    # 8 个玩家 + 8 个英雄实体
    for player_id in range(1, 9):
        entity_id = 1 + player_id
        hero_id = 10 + player_id
        lines.append(
            f"D 16:00:00.1000000 GameState.DebugPrintPower() - "
            f"Player EntityID={entity_id} PlayerID={player_id} "
            f"GameAccountId=[hi=11 lo={player_id}]")
        lines.append(_tag_line("PLAYER_ID", str(player_id)))
        lines.append(_tag_line("HERO_ENTITY", str(hero_id)))
        lines.append(_tag_line("HEALTH", "30"))
        lines.append(_tag_line("ARMOR", "0"))
        lines.append(_tag_line("PLAYER_TECH_LEVEL", "3"))
        lines.append(
            f"D 16:00:00.1000000 GameState.DebugPrintPower() - "
            f"FULL_ENTITY - Creating ID={hero_id} CardID=BG20_HERO_10{player_id}")
        lines.append(_tag_line("CARDTYPE", "HERO"))
        lines.append(_tag_line("ZONE", "PLAY"))
        lines.append(_tag_line("CONTROLLER", str(player_id)))
    # 我的战团（player 1）：Razorfen Geomancer 2/1；对手（player 2）：Risen Rider 3/1
    for entity_id, card_id, controller, pos, atk, health, extra in (
            (64, "BG20_100", "1", "1", "2", "1", ("TAUNT", "1")),
            (65, "BG20_101", "1", "2", "3", "2", ()),
            (100, "BG25_001", "2", "1", "3", "1", ("REBORN", "1")),
            (101, "BG20_102", "2", "2", "2", "2", ()),
    ):
        lines.append(
            f"D 16:00:00.1000000 GameState.DebugPrintPower() - "
            f"FULL_ENTITY - Creating ID={entity_id} CardID={card_id}")
        lines.append(_tag_line("CARDTYPE", "MINION"))
        lines.append(_tag_line("ZONE", "PLAY"))
        lines.append(_tag_line("CONTROLLER", controller))
        lines.append(_tag_line("ZONE_POSITION", pos))
        lines.append(_tag_line("ATK", atk))
        lines.append(_tag_line("HEALTH", health))
        lines.append(_tag_line("PREMIUM", "1" if entity_id == 65 else "0"))
        if extra:
            lines.append(_tag_line(*extra))
    lines += [
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=GameEntity tag=TURN value=8",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=GameEntity tag=BACON_COMBAT_DAMAGE_CAP value=7",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=GameEntity tag=BACON_COMBAT_DAMAGE_CAP_ENABLED"
        " value=1",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=GameEntity tag=BACON_IN_COMBAT_PHASE value=1",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_START "
        "BlockType=ATTACK Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 "
        "cardId=BG20_100 player=1] EffectCardId= EffectIndex=0 "
        "Target=[entityName=Risen Rider id=100 zone=PLAY zonePos=1 "
        "cardId=BG25_001 player=2] SubOption=-1",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=[entityName=Risen Rider id=100 zone=PLAY zonePos=1 "
        "cardId=BG25_001 player=2] tag=DAMAGE value=2",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=[entityName=Risen Rider id=100 zone=PLAY zonePos=1 "
        "cardId=BG25_001 player=2] tag=ZONE value=GRAVEYARD",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_END",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=[entityName=Battlegrounds Player id=3 zone=PLAY "
        "player=2] tag=HEALTH value=25",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=GameEntity tag=BACON_IN_COMBAT_PHASE value=0",
        "D 16:00:00.1000000 GameState.DebugPrintPower() - "
        "TAG_CHANGE Entity=GameEntity tag=TURN value=9",
    ]
    return "\n".join(lines)


#: 2 人构筑局：带 BG token 与 BACON_TRIPLE_UPGRADE_MINION_ID 单条 tag——
#: 必须**不**被判为酒馆战棋（本机 103 个真实录像就是这种）
CONSTRUCTED_LOG = "\n".join([
    "D 16:00:00.1 GameState.DebugPrintPower() - CREATE_GAME",
    "D 16:00:00.1 GameState.DebugPrintPower() - Player EntityID=2 PlayerID=1",
    "D 16:00:00.1 GameState.DebugPrintPower() - Player EntityID=3 PlayerID=2",
    "D 16:00:00.1 GameState.DebugPrintPower() -     tag=BACON_TRIPLE_UPGRADE_MINION_ID"
    " value=59510",
    "D 16:00:00.1 GameState.DebugPrintPower() -     tag=TECH_LEVEL value=4",
    "D 16:00:00.1 GameState.DebugPrintPower() -     CardID=BG31_BOB",
])


# ══════════════════════════════════════════════════════════════════════
# BobsBuddy 日志解析
# ══════════════════════════════════════════════════════════════════════


def test_parse_bobsbuddy_traces() -> None:
    traces, stats = T.parse_hdt_bobsbuddy_text(
        BOBSBUDDY_LOG, episode_id="ep_test")
    assert len(traces) == 2
    assert stats["sim_inputs"] == 2
    assert stats["parsed"] == 2
    assert stats["with_official_result"] == 2
    assert stats["with_bb_rates"] == 2

    first = traces[0]
    assert first.source == T.SOURCE_BOBSBUDDY
    assert first.turn == 1
    assert first.official_result == "win"
    assert first.official_lethal == "NoOneDied"
    assert first.bb_rates["win"] == pytest.approx(0.717)
    assert first.bb_rates["tie"] == pytest.approx(0.253)
    assert first.bb_iterations == 9996
    assert first.heroes == {"attacker": "Elise Starseeker",
                            "defender": "Ambassador Faelin"}
    # 额外检测效果（BG 秘密；真实日志里 Pack Tactics 会改变战斗结果）
    assert first.player.detected == [{"kind": "S", "value": "PackTactics"}]
    assert first.opponent.detected == []
    # 玩家：手牌与战团分离；名字带逗号/关键词/金色/脚本计数
    assert [m.name for m in first.player.hand] == ["Bream Counter"]
    assert [m.name for m in first.player.minions] == [
        "Goldrinn, the Great Wolf", "Risen Rider", "Monstrous Macaw"]
    gr = first.player.minions[0]
    assert (gr.atk, gr.health) == (8, 8)
    assert gr.tags["ScriptDataNum1"] == "8"
    assert first.player.minions[1].keywords == ["taunt", "reborn"]
    macaw = first.player.minions[2]
    assert macaw.golden is True and macaw.keywords == ["divine_shield"]
    # 对手：任务/奖励不是随从，进 unsupported；手牌内联解析
    assert [m.name for m in first.opponent.minions] == ["Gluttonous Trogg"]
    assert first.opponent.unsupported[0]["kind"] == "quest"
    assert [m.name for m in first.opponent.hand] == ["Tide Oracle Morgl"]
    assert first.opponent.hand[0].keywords == ["poisonous"]
    assert first.player.hero_power_id == "BG22_HERO_201p"
    assert first.player.hero_power_used is False
    assert first.player.second_hero_power_id == "BG34_HERO_000p"

    second = traces[1]
    assert second.turn == 2                       # 战斗发生在 turn 2
    assert second.official_result == "tie"
    assert second.player.minions[0].keywords == ["taunt"]
    assert second.opponent.minions[0].name == "Twilight Hatchling"
    # 空手牌 = 合法状态，不应被记成 missing
    assert second.player.hand == []
    assert "official_result" not in second.missing_fields


def test_parse_bobsbuddy_board_entry_tokens() -> None:
    golden = T.parse_bobsbuddy_board_entry("Monstrous Macaw 11/9, G, Div")
    assert golden["keywords"] == ["golden", "divine_shield"]
    comma_name = T.parse_bobsbuddy_board_entry(
        "Goldrinn, the Great Wolf 8/8, ScriptDataNum1=8, ScriptDataNum2=8")
    assert comma_name["name"] == "Goldrinn, the Great Wolf"
    assert comma_name["tags"] == {"ScriptDataNum1": "8", "ScriptDataNum2": "8"}
    quest = T.parse_bobsbuddy_board_entry(
        "BG24_Quest_124 (4/10): BG24_HERO_100_Buddyt")
    assert quest["kind"] == "quest"
    assert quest["card_id"] == "BG24_HERO_100_Buddyt"
    unknown = T.parse_bobsbuddy_board_entry("SpellCardEntity")
    assert unknown["kind"] == "unparsed"


def test_trace_roundtrip_and_privacy(tmp_path) -> None:
    traces, _ = T.parse_hdt_bobsbuddy_text(BOBSBUDDY_LOG, episode_id="ep_test")
    path = T.save_trace(traces[0], tmp_path)
    back = T.load_trace(path)
    assert back.to_dict() == traces[0].to_dict()
    assert back.trace_id == traces[0].trace_id
    text = path.read_text(encoding="utf-8")
    # 匿名化：不出现原始文件名 / 账号 / BattleTag / 玩家名
    assert "hdt_log" not in text
    assert "GameAccountId" not in text
    assert "PlayerName" not in text
    data = json.loads(text)
    assert data["schema"] == T.SCHEMA
    assert data["episode_id"] == "ep_test"


def test_trace_statistics() -> None:
    traces, _ = T.parse_hdt_bobsbuddy_text(BOBSBUDDY_LOG, episode_id="ep_test")
    stats = T.trace_statistics(traces)
    assert stats["traces"] == 2
    assert stats["sources"] == {"hdt_bobsbuddy": 2}
    assert stats["field_completeness"]["official_result"] == 1.0
    assert stats["field_completeness"]["bb_rates"] == 1.0
    assert stats["field_completeness"]["turn"] == 1.0
    assert "official_result" not in stats["missing_field_counts"]


def test_anonymize_source_is_stable_and_hides_name() -> None:
    a = T.anonymize_source("Player#1234 vs Enemy#5678 1234-010124.hdtreplay")
    b = T.anonymize_source("Player#1234 vs Enemy#5678 1234-010124.hdtreplay")
    assert a == b
    assert a.startswith("ep_") and len(a) == 15
    assert "Player" not in a and "#" not in a


# ══════════════════════════════════════════════════════════════════════
# Power.log BG 解析
# ══════════════════════════════════════════════════════════════════════


def test_bg_detection_strict_markers() -> None:
    bg_log = _build_bg_powerlog()
    assert T.is_battlegrounds_powerlog(bg_log) is True
    assert T.count_powerlog_players(bg_log) == 8
    # 2 人构筑局即使引用 BG token / BACON tag 也不能误判（真实语料教训）
    assert T.is_battlegrounds_powerlog(CONSTRUCTED_LOG) is False
    assert T.count_powerlog_players(CONSTRUCTED_LOG) == 2
    assert T.is_battlegrounds_powerlog(
        "x BACON_IN_COMBAT_PHASE y") is True


def test_parse_bg_powerlog_combat() -> None:
    traces, stats = T.parse_bg_powerlog_text(_build_bg_powerlog())
    assert stats["combats"] == 1
    assert stats["bacon_phase_seen"] is True
    assert stats["boundary_mode"] == "bacon_phase"
    trace = traces[0]
    assert trace.turn == 8
    assert trace.source == T.SOURCE_POWERLOG
    # 战团快照：站位顺序、属性、关键词、金色
    assert [m.card_id for m in trace.player.minions] == ["BG20_100", "BG20_101"]
    assert (trace.player.minions[0].atk, trace.player.minions[0].health) == (2, 1)
    assert trace.player.minions[0].keywords == ["taunt"]
    assert trace.player.minions[1].golden is True
    assert [m.card_id for m in trace.opponent.minions] == ["BG25_001", "BG20_102"]
    assert trace.opponent.minions[0].keywords == ["reborn"]
    # 英雄
    assert trace.player.hero_card_id == "BG20_HERO_101"
    assert trace.opponent.hero_card_id == "BG20_HERO_102"
    assert trace.player.tier == 3
    # 事件流：attack → damage → death（按日志顺序）
    kinds = [event.kind for event in trace.events]
    assert kinds[:3] == ["attack", "damage", "death"]
    attack = trace.events[0]
    assert (attack.actor_side, attack.actor_slot) == ("player", 0)
    assert (attack.target_side, attack.target_slot) == ("opponent", 0)
    damage = trace.events[1]
    assert damage.amount == 2
    assert (damage.target_side, damage.target_slot) == ("opponent", 0)
    # 官方伤害上限 tag（服务端 GameEntity；供 harness 注入引擎）
    assert trace.damage_cap == 7
    assert trace.damage_cap_enabled is True
    # 结果：对手英雄 30 → 25 掉血 = 我方胜
    assert trace.official_result == "win"
    assert trace.official_damage == {"player": 0, "opponent": 5}


def test_parse_bg_powerlog_tolerates_unknown_lines() -> None:
    text = _build_bg_powerlog() + "\nD 16:00:00.1 GameState.DebugPrintPower() - 未来未知行\n"
    traces, stats = T.parse_bg_powerlog_text(text)
    assert stats["combats"] == 1


def test_golden_keyword_line_on_hero_is_parsed() -> None:
    # tag 行在 Player 块之后仍然归属该玩家（pending entity 语义）
    traces, _ = T.parse_bg_powerlog_text(_build_bg_powerlog())
    band = traces[0].player
    assert band.health == 30
    assert band.missing_fields == []


def _build_pseudo_summon_powerlog() -> str:
    """复现 e057：战斗结束 SETASIDE 副本还原回 PLAY，**不是召唤**。

    真实日志里副本实体带 ``COPIED_FROM_ENTITY_ID`` /
    ``BACON_DIED_LAST_COMBAT`` 标记；旧逻辑记 summon → 终局存活虚增 →
    官方结果误判（实际双方全灭 = tie）。
    """
    def tag(name: str, value: str) -> str:
        return f"D 16:00:00.1 GameState.DebugPrintPower() -         tag={name} value={value}"

    lines = [
        "D 16:00:00.1 GameState.DebugPrintPower() - CREATE_GAME",
        "D 16:00:00.1 GameState.DebugPrintPower() -     GameEntity EntityID=7",
        tag("GAME_SEED", "12345"),
        "D 16:00:00.1 GameState.DebugPrintPower() -     Player EntityID=8 PlayerID=3 GameAccountId=[hi=11 lo=1]",
        "D 16:00:00.1 GameState.DebugPrintPower() -     Player EntityID=9 PlayerID=11 GameAccountId=[hi=0 lo=0]",
        "D 16:00:00.1 GameState.DebugPrintPower() -     FULL_ENTITY - Creating ID=64 CardID=BG26_135",
        tag("CARDTYPE", "MINION"),
        tag("ZONE", "PLAY"),
        tag("CONTROLLER", "3"),
        tag("ZONE_POSITION", "1"),
        tag("ATK", "3"),
        tag("HEALTH", "1"),
        "D 16:00:00.1 GameState.DebugPrintPower() -     FULL_ENTITY - Creating ID=65 CardID=BG35_814",
        tag("CARDTYPE", "MINION"),
        tag("ZONE", "PLAY"),
        tag("CONTROLLER", "11"),
        tag("ZONE_POSITION", "1"),
        tag("ATK", "3"),
        tag("HEALTH", "6"),
        "D 16:00:00.1 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=TURN value=8",
        "D 16:00:00.1 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=BACON_IN_COMBAT_PHASE value=1",
        "D 16:00:00.1 GameState.DebugPrintPower() - BLOCK_START BlockType=ATTACK Entity=[entityName=Busker id=64 zone=PLAY zonePos=1 cardId=BG26_135 player=3] EffectCardId= EffectIndex=0 Target=0 SubOption=-1",
        "D 16:00:00.1 GameState.DebugPrintPower() -     TAG_CHANGE Entity=GameEntity tag=PROPOSED_ATTACKER value=64",
        "D 16:00:00.1 GameState.DebugPrintPower() -     TAG_CHANGE Entity=GameEntity tag=PROPOSED_DEFENDER value=65",
        "D 16:00:00.1 GameState.DebugPrintPower() -     TAG_CHANGE Entity=65 tag=DAMAGE value=3",
        "D 16:00:00.1 GameState.DebugPrintPower() -     TAG_CHANGE Entity=65 tag=ZONE value=GRAVEYARD",
        "D 16:00:00.1 GameState.DebugPrintPower() -     TAG_CHANGE Entity=64 tag=ZONE value=GRAVEYARD",
        "D 16:00:00.1 GameState.DebugPrintPower() - BLOCK_END",
        # 战斗结束：战团副本（SETASIDE）还原回 PLAY —— 旧逻辑会记 summon
        "D 16:00:00.1 GameState.DebugPrintPower() -     FULL_ENTITY - Creating ID=904 CardID=BG26_135",
        tag("CARDTYPE", "MINION"),
        tag("ZONE", "SETASIDE"),
        tag("CONTROLLER", "3"),
        tag("COPIED_FROM_ENTITY_ID", "64"),
        tag("BACON_DIED_LAST_COMBAT", "1"),
        "D 16:00:00.1 GameState.DebugPrintPower() -     TAG_CHANGE Entity=[entityName=Busker id=904 zone=SETASIDE zonePos=0 cardId=BG26_135 player=3] tag=ZONE value=PLAY",
        "D 16:00:00.1 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=BACON_IN_COMBAT_PHASE value=0",
    ]
    return "\n".join(lines)


def test_powerlog_setaside_copy_restore_is_not_summon() -> None:
    traces, _ = T.parse_bg_powerlog_text(_build_pseudo_summon_powerlog())
    assert len(traces) == 1
    trace = traces[0]
    # 双方全灭 → tie（旧逻辑因伪 summon 误判 win）
    assert trace.official_result == T.RESULT_TIE
    assert not any(event.kind == "summon" for event in trace.events)
    assert not any(event.card_id == "BG26_135" and event.kind == "summon"
                   for event in trace.events)
    # GAME_SEED 作为可选元数据进入 trace
    assert trace.game_seed == 12345
    assert "game_seed" in trace.to_dict()


def test_hdt_159_card_ids_resolved_from_names() -> None:
    """HDT 1.59.3 fixture：BobsBuddy 战团行只有名字/属性，无 cardId=。

    真实会话（第二局 22:14–22:32）抽 10 条轨迹；解析后 minion `card_id`
    全空。用 CardDB 名称索引补齐后：minion card_id 100% 解析、hero 部分
    解析（部分对手英雄名不在数据中），从而能做战团签名/逐卡交叉。
    """
    fixture = ROOT / "runs" / "hdt_logs_2214" / "hdt_log.txt"
    if not fixture.exists():
        pytest.skip("HDT 1.59.3 fixture 缺失（runs/ 不随仓库分发）")
    text = fixture.read_text(encoding="utf-8", errors="replace")
    traces, stats = T.parse_hdt_bobsbuddy_text(text, episode_id="ep_hdt159")
    assert len(traces) == 10
    assert stats["with_bb_rates"] == 10
    # 原始格式确实没有 cardId（否则本测试无意义）
    assert all(m.card_id is None for t in traces
               for b in (t.player, t.opponent) for m in b.minions)
    from tools.diff_extract_replays import _card_name_index
    resolved = T.resolve_trace_card_ids(traces, _card_name_index())
    assert resolved["unresolved_minions"] == 0
    assert all(m.card_id for t in traces
               for b in (t.player, t.opponent) for m in b.minions)
    # 已知卡：Southsea Busker → BG26_135
    ids = {m.card_id for t in traces for b in (t.player, t.opponent)
           for m in b.minions}
    assert "BG26_135" in ids
    # 战团签名现在包含 card_id（可用于 Power.log 同局交叉）
    assert any("BG26_135" in t.signature() for t in traces)


def test_powerlog_official_result_cross_sessions() -> None:
    """B/C 真机回归：official_result 修复后 Power.log 与 HDT Validate 对齐。

    C 局修复点：round3/4/5 由 tie 纠正为 win/loss/loss（英雄掉血纠偏）；
    round10 HDT 在游戏结束前无 Validate（BB 预测 Loss，Power=loss）。
    """
    p_b = ROOT / "runs" / "powerlog_2214" / "Power.log"
    p_c = ROOT / "runs" / "powerlog_2240" / "Power.log"
    if not (p_b.exists() and p_c.exists()):
        pytest.skip("真机 Power.log 缺失（runs/ 不随仓库分发）")

    def load_power(path):
        traces, _ = T.parse_bg_powerlog_text(
            path.read_text(encoding="utf-8", errors="replace"),
            episode_id="ep_cross")
        return {((t.turn or 0) // 2): t for t in traces}

    b = load_power(p_b)
    # B 局 10/10（HDT Validate 序列）
    expected_b = {1: "loss", 2: "tie", 3: "win", 4: "loss", 5: "win",
                  6: "tie", 7: "loss", 8: "win", 9: "loss", 10: "loss"}
    assert {r: t.official_result for r, t in b.items()} == expected_b

    c = load_power(p_c)
    # C 局关键 4 条：round3/4/5 修正 + round10（HDT 无 Validate，BB=loss）
    assert c[3].official_result == "win"
    assert c[4].official_result == "loss"
    assert c[5].official_result == "loss"
    assert c[10].official_result == "loss"
    # C 其余与 HDT Validate 一致
    expected_c = {1: "tie", 2: "tie", 3: "win", 4: "loss", 5: "loss",
                  6: "win", 7: "loss", 8: "loss", 9: "win", 10: "loss"}
    assert {r: t.official_result for r, t in c.items()} == expected_c
