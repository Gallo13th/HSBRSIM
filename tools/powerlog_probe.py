#!/usr/bin/env python
"""Power.log 探针：解析真实日志并打印摘要；没有真实日志时用内置样例自测。

用法::

    python tools/powerlog_probe.py                 # 自动找默认路径的 Power.log
    python tools/powerlog_probe.py --log path/Power.log
    python tools/powerlog_probe.py --log "C:/Program Files (x86)/Hearthstone/Logs"
    python tools/powerlog_probe.py --sample        # 强制使用内置样例
    python tools/powerlog_probe.py --tail-bytes 2000000 --max-lines 200000

行为
----
1. 按 ``--log`` → 默认路径顺序查找 ``Power.log``（只读，不修改游戏目录）；
2. 找到则解析（默认只读文件末尾 2 MiB，避免早期对局太大）；
3. 找不到则解析内置样例，并打印"已检查过的路径"；
4. 输出：行数 / 事件统计 / 实体数 / turn 推进 / 关键 tag / block / 棋盘摘要。

退出码始终为 0（探针只做诊断；解析失败会打印异常摘要，不崩溃）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsbg.bridge.powerlog import (  # noqa: E402
    EVENT_BLOCK_START,
    EVENT_TAG_CHANGE,
    PowerLogParser,
)

# ── 默认日志路径（只读）──────────────────────────────────────────────
GAME_DIR = Path(r"C:\Program Files (x86)\Hearthstone")
DEFAULT_LOG_DIRS: List[Path] = [
    GAME_DIR / "Logs",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Blizzard" / "Hearthstone" / "Logs",
    Path(os.environ.get("USERPROFILE", "")) / "Documents" / "Hearthstone" / "Logs",
    Path(os.environ.get("USERPROFILE", "")) / "Documents" / "Blizzard" / "Hearthstone" / "Logs",
]

#: 内置样例：覆盖 CREATE_GAME / Player / FULL_ENTITY / TAG_CHANGE / SHOW_ENTITY /
#: BLOCK_START / BLOCK_END 以及一条未知行。格式与真实 Power.log 保持一致。
SAMPLE_LOG: Sequence[str] = (
    "D 16:00:00.1000000 GameState.DebugPrintPower() - CREATE_GAME",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - GameEntity EntityID=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=GAME_SEED value=424242",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - Player EntityID=2 PlayerID=1 GameAccountId=[hi=1 lo=2]",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=PLAYER_ID value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=HERO_ENTITY value=3",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=HEALTH value=40",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=RESOURCES value=3",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=PLAYER_TECH_LEVEL value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=TURN value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - Player EntityID=9 PlayerID=5 GameAccountId=[hi=3 lo=4]",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=PLAYER_ID value=5",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=HEALTH value=40",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=3 CardID=BG20_HERO_100",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=64 CardID=",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=ZONE value=SETASIDE",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - FULL_ENTITY - Updating [entityName=Alleycat id=64 zone=HAND zonePos=1 cardId=BG20_100 player=1] CardID=",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=Alleycat id=64 zone=HAND zonePos=1 cardId=BG20_100 player=1] tag=ZONE value=PLAY",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] tag=ATK value=2",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] tag=HEALTH value=3",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - SHOW_ENTITY - Updating Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] CardID=BG20_100",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_START BlockType=PLAY Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] EffectCardId= EffectIndex=0 Target=0 SubOption=-1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_END",
    "D 16:00:00.1000000 GameState.DebugPrintOptions() - option 0 type=END_TURN mainEntity= error=INVALID",
    "D 16:00:00.1000000 GameState.DebugPrintOptions() - option 1 type=POWER mainEntity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] error=INVALID",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=BACON_IN_COMBAT_PHASE value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=TURN value=2",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_START BlockType=TRIGGER Entity=GameEntity EffectCardId= EffectIndex=14 Target=0 SubOption=-1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_END",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - 未知行-用于验证容错",
)


def find_power_logs(extra: Optional[Path | str] = None) -> List[Path]:
    """返回候选 ``Power.log`` 路径（按修改时间倒序）。"""
    candidates: List[Path] = []
    explicit = Path(extra) if extra else None
    if explicit is not None:
        if explicit.is_file():
            candidates.append(explicit)
        elif explicit.is_dir():
            candidates.extend(
                p for p in explicit.rglob("Power.log") if p.is_file()
            )
    for directory in DEFAULT_LOG_DIRS:
        if not directory or not directory.is_dir():
            continue
        direct = directory / "Power.log"
        if direct.is_file():
            candidates.append(direct)
        try:
            candidates.extend(
                p for p in directory.glob("*/Power.log") if p.is_file()
            )
        except OSError:
            pass
    unique: Dict[str, Path] = {}
    for path in candidates:
        try:
            unique[str(path.resolve())] = path
        except OSError:
            unique[str(path)] = path
    return sorted(unique.values(), key=lambda p: _safe_mtime(p), reverse=True)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _checked_paths_text() -> str:
    return "\n".join(f"  - {p}" for p in DEFAULT_LOG_DIRS)


def parse_stream(parser: PowerLogParser, lines: Iterable[str]) -> int:
    count = 0
    for line in lines:
        parser.feed(line)
        count += 1
    return count


def print_summary(parser: PowerLogParser, source: str, line_count: int) -> None:
    state = parser.game_state()
    stats = parser.summary()
    print("=" * 78)
    print(f"来源: {source}")
    print(f"行数: {line_count}  实体: {stats['entity_count']}  玩家: {stats['player_count']}  "
          f"turn: {stats['turn']}  phase: {stats['phase'] or '(未标注)'}  "
          f"game_index: {stats['game_index']}")
    print(f"事件统计: {json.dumps(stats['events_by_kind'], ensure_ascii=False)}")
    print(f"跳过 PowerTaskList 行: {stats['tasklist_lines']}  未知行: {stats['unknown_lines']}  "
          f"解析异常: {stats['parse_errors']}  其他 GameState 行: {stats.get('other_lines', 0)}")

    # turn 推进：从 TAG_CHANGE TURN 事件里抽取（去重连续重复）
    turns: List[str] = []
    for event in parser.events:
        if event.kind == EVENT_TAG_CHANGE and event.tag == "TURN":
            if not turns or turns[-1] != event.value:
                turns.append(event.value)
    if turns:
        print(f"turn 推进: {' -> '.join(turns)}")

    # 关键 tag 统计
    tag_counter = Counter(event.tag for event in parser.events if event.kind == EVENT_TAG_CHANGE)
    if tag_counter:
        print(f"TAG_CHANGE 热tag: {json.dumps(tag_counter.most_common(12), ensure_ascii=False)}")

    # block 统计
    block_counter = Counter(event.block_type for event in parser.events if event.kind == EVENT_BLOCK_START)
    if block_counter:
        print(f"BLOCK_START 按类型: {json.dumps(block_counter.most_common(), ensure_ascii=False)}")

    # 棋盘摘要
    board = [
        e for e in parser.entities.values()
        if e.zone == "PLAY" and e.tag("CARDTYPE") == "MINION"
    ]
    if board:
        print("PLAY 区随从:")
        for entity in sorted(board, key=lambda e: (e.controller, e.entity_id))[:12]:
            print(f"  eid={entity.entity_id:<5d} card={entity.card_id or '(未知)':<18s} "
                  f"ctrl={entity.controller} atk={entity.int_tag('ATK')} hp={entity.int_tag('HEALTH')} "
                  f"tags={len(entity.tags)}")
    if parser.last_options:
        print(f"最后一次 DebugPrintOptions: {len(parser.last_options)} 个 option")
    if parser.last_choice:
        print(f"最后一次 EntityChoices: {json.dumps(parser.last_choice, ensure_ascii=False)}")
    print("game_state 预览:")
    print(json.dumps(state, ensure_ascii=False)[:800] + ("..." if len(json.dumps(state, ensure_ascii=False)) > 800 else ""))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Power.log 探针（真实日志 / 内置样例）")
    parser.add_argument("--log", default=None, help="Power.log 文件或 Logs 目录")
    parser.add_argument("--sample", action="store_true", help="强制使用内置样例")
    parser.add_argument("--tail-bytes", type=int, default=2 * 1024 * 1024,
                        help="只解析文件末尾 N 字节（默认 2MiB，0=全文件）")
    parser.add_argument("--max-lines", type=int, default=None, help="最多解析 N 行")
    parser.add_argument("--include-tasklist", action="store_true",
                        help="同时解析 PowerTaskList.* 重复消息")
    args = parser.parse_args(argv)

    power_parser = PowerLogParser(include_tasklist=args.include_tasklist)

    if args.sample:
        line_count = parse_stream(power_parser, SAMPLE_LOG)
        print("[样例模式] 未读取真实日志；以下为内置样例解析结果。")
        print_summary(power_parser, "内置样例（模拟真实 Power.log 行格式）", line_count)
        print("=" * 78)
        print("说明: 本机未找到真实 Power.log 时这是预期行为；真实对局请先按")
        print('      log.config 打开 [Power] FilePrinting=true，重启炉石后从新一局开始。')
        return 0

    logs = find_power_logs(args.log)
    if not logs:
        print("[未找到真实 Power.log] 已检查以下路径（只读）：")
        print(_checked_paths_text())
        if args.log:
            print(f"  - 指定路径: {args.log}")
        print("改用内置样例做自测。\n")
        line_count = parse_stream(power_parser, SAMPLE_LOG)
        print_summary(power_parser, "内置样例（模拟真实 Power.log 行格式）", line_count)
        return 0

    log_path = logs[0]
    print(f"发现 {len(logs)} 个 Power.log，使用最新的: {log_path}")
    try:
        tail_bytes = args.tail_bytes if args.tail_bytes and args.tail_bytes > 0 else None
        line_count = power_parser.feed_file(
            log_path,
            tail_bytes=tail_bytes,
            max_lines=args.max_lines,
        )
        print_summary(power_parser, str(log_path), line_count)
    except Exception:  # noqa: BLE001 - 探针不崩溃
        print("[解析失败] 已捕获异常，打印摘要：")
        traceback.print_exc(limit=3)
        print_summary(power_parser, str(log_path), 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
