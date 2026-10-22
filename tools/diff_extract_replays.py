"""官方战斗轨迹抽取 CLI（``official_combat_trace.v1``）。

数据源
------
1. ``--replays``（默认 HDT 录像目录）：``*.hdtreplay`` = zip 内
   ``output_log.txt``（完整 Power.log）。**只读**；按严格 BG 信号过滤，
   非 BG 局写入跳过原因统计。⚠️ 本机全部 1,365 个录像都是 2 人构筑局
   （见 docs/DIFF_HARNESS.md §2.1），因此该源当前命中 0 场——采集到真实
   BG ``Power.log`` 后用 ``--powerlog`` 即可。
2. ``--hdt-logs``（默认 HDT 会话日志目录）：``hdt_log*.txt`` 里的
   BobsBuddy ``Simulation Input/Output`` + 官方 ``result=`` 校验结果。
   **这是本机唯一现成的真实 BG 战斗语料**（679 场，覆盖 27 个会话）。
3. ``--powerlog``：显式指定一个/多个 Power.log 文件或目录（未来采集用）。

输出
----
``<out>/<trace_id>.json``（每场战斗一个）+ ``<out>/index.json``（统计）。
``trace_id`` 由「来源 + 匿名 episode + 战斗序号 + 回合 + 战团签名」哈希而来，
因此**幂等**：重复运行不会产生重复轨迹，已存在的文件默认跳过（``--force`` 覆盖）。

隐私：不落盘玩家名 / BattleTag / GameAccountId / 原始文件名；episode id 是
``sha256(文件名)[:12]``。Power.log 里的 ``GameAccountId`` 不解析、不保存。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.bridge import trace as T  # noqa: E402

DEFAULT_REPLAYS = (Path.home() / "AppData" / "Roaming"
                   / "HearthstoneDeckTracker" / "Replays")
DEFAULT_HDT_LOGS = (Path.home() / "AppData" / "Roaming"
                    / "HearthstoneDeckTracker" / "Logs")
DEFAULT_OUT = ROOT / "runs" / "official_traces"
DEFAULT_JSON = ROOT / "runs" / "diff_extract_report.json"

#: 录像里判定「不是 BG」时记录的主因（用于如实报告阻塞点）
_SKIP_NO_BG_MARKER = "not_battlegrounds"


def read_hdtreplay_log(path: Path) -> str:
    """读取 ``.hdtreplay``（zip）里的 ``output_log.txt``。"""
    with zipfile.ZipFile(path) as archive:
        name = next((n for n in archive.namelist()
                     if n.lower().endswith((".log", ".txt"))), None)
        if name is None:
            return ""
        return archive.read(name).decode("utf-8", errors="replace")


def scan_replays(replays_dir: Path, *, limit: Optional[int] = None,
                 powerlog_mode: bool = False) -> Tuple[List[T.OfficialCombatTrace],
                                                       Dict[str, Any]]:
    """扫描 HDT 录像目录，抽 BG 战斗轨迹（本机预期 0 场）。"""
    files = sorted(replays_dir.glob("*.hdtreplay")) if replays_dir.exists() else []
    scanned = files[: int(limit)] if limit is not None else files
    traces: List[T.OfficialCombatTrace] = []
    stats: Dict[str, Any] = {
        "dir": str(replays_dir),
        "files_total": len(files),
        "files_scanned": 0,
        "battlegrounds_games": 0,
        "combats": 0,
        "skipped": {},
        "diagnostics": {
            "with_tb_baconshop": 0,
            "with_player_tech_level": 0,
            "with_bacon_combat_phase": 0,
            "with_bg_card_ids_only": 0,
            "with_bg_triple_tag_only": 0,
            "players_8": 0,
            "read_errors": 0,
        },
        "files": [],
    }
    for path in scanned:
        stats["files_scanned"] += 1
        episode_id = T.anonymize_source(path.name)
        try:
            text = read_hdtreplay_log(path)
        except (OSError, zipfile.BadZipFile) as exc:
            stats["diagnostics"]["read_errors"] += 1
            stats["files"].append({"episode_id": episode_id,
                                   "error": type(exc).__name__})
            continue
        if not text:
            stats["files"].append({"episode_id": episode_id,
                                   "error": "empty_log"})
            continue
        is_bg = T.is_battlegrounds_powerlog(text)
        players = T.count_powerlog_players(text)
        has_tb = "TB_BaconShop" in text
        has_tech = "PLAYER_TECH_LEVEL" in text
        has_phase = "BACON_IN_COMBAT_PHASE" in text
        has_bg_card = "CardID=BG" in text
        has_triple_tag = "BACON_TRIPLE_UPGRADE_MINION_ID" in text
        stats["diagnostics"]["with_tb_baconshop"] += int(has_tb)
        stats["diagnostics"]["with_player_tech_level"] += int(has_tech)
        stats["diagnostics"]["with_bacon_combat_phase"] += int(has_phase)
        stats["diagnostics"]["with_bg_triple_tag_only"] += int(
            has_triple_tag and not is_bg)
        stats["diagnostics"]["players_8"] += int(players >= 8)
        if not is_bg:
            if has_bg_card:
                stats["diagnostics"]["with_bg_card_ids_only"] += 1
            stats["skipped"][_SKIP_NO_BG_MARKER] = \
                stats["skipped"].get(_SKIP_NO_BG_MARKER, 0) + 1
            stats["files"].append({
                "episode_id": episode_id,
                "skip": _SKIP_NO_BG_MARKER,
                "players": players,
                "lines": text.count("\n") + 1,
            })
            continue
        stats["battlegrounds_games"] += 1
        game_traces, parse_stats = T.parse_bg_powerlog_text(
            text, episode_id=episode_id)
        stats["combats"] += len(game_traces)
        stats["files"].append({"episode_id": episode_id,
                               "battlegrounds": True,
                               "parse": parse_stats})
        traces.extend(game_traces)
    return traces, stats


def _card_name_index() -> Dict[str, str]:
    """卡名 → card_id（来自 data/ 的 JSON；不依赖引擎运行）。

    HDT BobsBuddy 行只有名字（HDT 1.59.3 亦无 cardId=），需要补齐
    ``card_id`` 才能做战团签名/逐卡交叉；Power.log 原始 id 不被覆盖。
    """
    index: Dict[str, str] = {}
    for fname in ("bg_cards.json", "bg_heroes.json", "bg_hero_powers.json",
                  "bg_pool_minions.json", "bg_pool_spells.json"):
        path = ROOT / "data" / fname
        if not path.exists():
            continue
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name, card_id = entry.get("name"), entry.get("id")
            if name and card_id:
                index.setdefault(str(name), str(card_id))
    return index


def scan_hdt_logs(log_dir: Path, *, limit: Optional[int] = None,
                  max_combats: Optional[int] = None,
                  resolve_card_ids: bool = True,
                  ) -> Tuple[List[T.OfficialCombatTrace], Dict[str, Any]]:
    traces, report = T.iter_hdt_bobsbuddy_traces(
        log_dir, limit_files=limit, max_combats_per_file=max_combats)
    report["dir"] = str(log_dir)
    if resolve_card_ids and traces:
        try:
            name_index = _card_name_index()
            report["card_id_resolution"] = T.resolve_trace_card_ids(
                traces, name_index)
        except Exception as exc:  # noqa: BLE001 - 解析失败不阻塞抽取
            report["card_id_resolution"] = {
                "error": f"{type(exc).__name__}: {exc}"}
    return traces, report


def scan_powerlog_path(path: Path, *, limit: Optional[int] = None,
                       ) -> Tuple[List[T.OfficialCombatTrace], Dict[str, Any]]:
    """显式 Power.log（文件或目录，未来真实 BG 采集用）。"""
    if path.is_dir():
        files = sorted(path.glob("*.log")) + sorted(path.glob("*.txt"))
    else:
        files = [path]
    if limit is not None:
        files = files[: int(limit)]
    traces: List[T.OfficialCombatTrace] = []
    stats: Dict[str, Any] = {"paths": [str(f) for f in files],
                             "battlegrounds_games": 0, "combats": 0,
                             "skipped": {}}
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover
            stats["skipped"][f"read_error:{type(exc).__name__}"] = (
                stats["skipped"].get(f"read_error:{type(exc).__name__}", 0) + 1)
            continue
        if not T.is_battlegrounds_powerlog(text):
            stats["skipped"][_SKIP_NO_BG_MARKER] = \
                stats["skipped"].get(_SKIP_NO_BG_MARKER, 0) + 1
            continue
        stats["battlegrounds_games"] += 1
        file_traces, parse_stats = T.parse_bg_powerlog_text(
            text, episode_id=T.anonymize_source(file_path.name))
        stats["combats"] += len(file_traces)
        stats.setdefault("files", []).append({"parse": parse_stats})
        traces.extend(file_traces)
    return traces, stats


def write_traces(traces: Sequence[T.OfficialCombatTrace], out_dir: Path,
                 *, force: bool = False, prune: bool = False) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    existing = 0
    keep = {f"{trace.trace_id}.json" for trace in traces}
    for trace in traces:
        path = out_dir / f"{trace.trace_id}.json"
        if path.exists() and not force:
            existing += 1
            continue
        T.save_trace(trace, out_dir)
        written += 1
    pruned = 0
    if prune and out_dir.exists():
        for path in out_dir.glob("*.json"):
            if path.name == "index.json" or path.name in keep:
                continue
            path.unlink()
            pruned += 1
    return {"written": written, "existing": existing, "pruned": pruned,
            "total": len(traces), "out_dir": str(out_dir)}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="官方 BG 战斗轨迹抽取（Power.log 录像 + HDT BobsBuddy 日志）")
    parser.add_argument("--replays", default=str(DEFAULT_REPLAYS),
                        help="HDT 录像目录（只读）")
    parser.add_argument("--hdt-logs", default=str(DEFAULT_HDT_LOGS),
                        help="HDT 会话日志目录（BobsBuddy 轨迹源）")
    parser.add_argument("--powerlog", default=None,
                        help="显式 Power.log 文件/目录（未来真实 BG 采集用）")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="轨迹输出目录")
    parser.add_argument("--limit", type=int, default=None,
                        help="每个源最多扫描多少个游戏/日志文件")
    parser.add_argument("--combat-limit", type=int, default=None,
                        help="最多写出多少条战斗轨迹（跨源截断）")
    parser.add_argument("--max-combats-per-file", type=int, default=None,
                        help="每个 HDT 会话日志最多抽多少场战斗")
    parser.add_argument("--sources", default="replays,hdt",
                        help="逗号分隔：replays,hdt,powerlog")
    parser.add_argument("--json", default=str(DEFAULT_JSON),
                        help="抽取统计报告路径")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的轨迹文件（默认跳过=幂等）")
    parser.add_argument("--prune", action="store_true",
                        help="删除输出目录里不属于本次结果的旧轨迹文件"
                             "（默认关闭：避免 --limit 小样本运行时误删全量语料）")
    parser.set_defaults(prune=False)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    sources = {s.strip() for s in str(args.sources).split(",") if s.strip()}
    started = time.time()
    all_traces: List[T.OfficialCombatTrace] = []
    report: Dict[str, Any] = {
        "schema": "diff_extract_report.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "settings": {
            "limit": args.limit,
            "combat_limit": args.combat_limit,
            "sources": sorted(sources),
            "out": args.out,
        },
    }
    if "replays" in sources:
        traces, stats = scan_replays(Path(args.replays), limit=args.limit)
        all_traces.extend(traces)
        report["replays"] = stats
    if "hdt" in sources:
        traces, stats = scan_hdt_logs(
            Path(args.hdt_logs), limit=args.limit,
            max_combats=args.max_combats_per_file)
        all_traces.extend(traces)
        report["hdt_logs"] = stats
    if "powerlog" in sources and args.powerlog:
        traces, stats = scan_powerlog_path(Path(args.powerlog), limit=args.limit)
        all_traces.extend(traces)
        report["powerlog"] = stats
    if args.combat_limit is not None:
        all_traces = all_traces[: int(args.combat_limit)]
    written = write_traces(all_traces, Path(args.out), force=args.force,
                           prune=args.prune)
    report["traces"] = T.trace_statistics(all_traces)
    report["write"] = written
    report["elapsed_seconds"] = round(time.time() - started, 2)
    if source_replays := report.get("replays"):
        report["blockers"] = _blockers(source_replays,
                                       report.get("hdt_logs") or {})
    index_path = Path(args.out) / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    json_path = Path(args.json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    if not args.quiet:
        _print_summary(report)
    return 0


def _blockers(replays: Dict[str, Any], hdt: Dict[str, Any]
              ) -> List[Dict[str, Any]]:
    """如实记录「真实 BG Power.log 不可得」这个阻塞点与替代来源。"""
    blockers: List[Dict[str, Any]] = []
    if replays.get("battlegrounds_games", 0) == 0:
        blockers.append({
            "blocker": "no_battlegrounds_powerlog",
            "detail": (
                f"录像目录 {replays.get('dir')} 共 {replays.get('files_total')} "
                f"个 .hdtreplay，严格 BG 信号命中 0 场；"
                f"players>=8 的文件 {replays['diagnostics']['players_8']} 个、"
                f"含 TB_BaconShop {replays['diagnostics']['with_tb_baconshop']} 个、"
                f"含 PLAYER_TECH_LEVEL "
                f"{replays['diagnostics']['with_player_tech_level']} 个、"
                f"仅引用 BG 卡 id 的构筑局 "
                f"{replays['diagnostics']['with_bg_card_ids_only']} 个"),
            "workaround": "改用 HDT BobsBuddy 会话日志（source=hdt_bobsbuddy）",
            "future": "采集真实 BG 后：--powerlog <Power.log>",
        })
    if hdt and hdt.get("parsed", 0) > 0:
        blockers.append({
            "blocker": "official_combat_corpus_is_bobsbuddy_log",
            "detail": (f"HDT 会话日志抽出 {hdt.get('parsed')} 场真实 BG 战斗"
                       f"（{hdt.get('files_scanned')} 个日志文件）；"
                       "官方结果来自 ValidateSimulationResultAsync，"
                       "BobsBuddy 概率只是第二实现参照"),
        })
    return blockers


def _print_summary(report: Dict[str, Any]) -> None:
    traces = report.get("traces") or {}
    print(f"[extract] traces={traces.get('traces', 0)} "
          f"results={traces.get('results', {})} "
          f"completeness={traces.get('field_completeness', {})}")
    replays = report.get("replays")
    if replays:
        print(f"[extract] replays: scanned={replays['files_scanned']} "
              f"bg_games={replays['battlegrounds_games']} "
              f"skipped={replays['skipped']}")
    hdt = report.get("hdt_logs")
    if hdt:
        print(f"[extract] hdt_logs: files={hdt.get('files_scanned')} "
              f"combats={hdt.get('parsed')}")
    write = report.get("write") or {}
    print(f"[extract] wrote={write.get('written')} "
          f"existing={write.get('existing')} -> {write.get('out_dir')}")


if __name__ == "__main__":
    raise SystemExit(main())
