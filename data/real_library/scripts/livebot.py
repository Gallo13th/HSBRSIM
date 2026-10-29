#!/usr/bin/env python
"""自动代打采集入口（默认 dry-run，安全第一）。

用法::

    # 1) 先验证：不点击任何真实输入，打印每一步计划（无游戏也能跑模拟）
    python scripts/livebot.py --games 5 --dry-run
    python scripts/livebot.py --games 2 --dry-run --simulate

    # 2) 查看/覆盖坐标
    python scripts/livebot.py --list-coords
    python scripts/livebot.py --set coords.points.end_turn=0.93,0.60 --show-config

    # 3) 真实代打（需要游戏已启动；F12 暂停/恢复）
    python scripts/livebot.py --games 20 --live

安全
----
* 不带 ``--live`` 时**绝不**发送真实鼠标/键盘事件（dry-run 只打印 ``[DRY]/[PLAN]``）；
* ``--live`` 需要找到 Hearthstone 窗口，否则直接报错退出（不会乱点桌面）；
* 产物写到 ``runs/live/<mode>_<时间戳>/``（records.jsonl / events.jsonl /
  summary.json / config_snapshot.json），错误截图在 ``runs/live/`` 下。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from hsbg.live.config import DEFAULT_CONFIG_PATH, LiveConfig, load_config  # noqa: E402
from hsbg.live.runner import LiveBot, SimulatedWatcher  # noqa: E402
from hsbg.live.wininput import (  # noqa: E402
    InputController,
    WindowNotFoundError,
    find_hearthstone_window,
)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python scripts/livebot.py",
        description="炉石酒馆战棋自动代打采集（默认 dry-run）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/livebot.py --games 5 --dry-run\n"
            "  python scripts/livebot.py --games 2 --dry-run --simulate\n"
            "  python scripts/livebot.py --list-coords\n"
            "  python scripts/livebot.py --games 20 --live\n"
        ),
    )
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                   help="配置文件路径（默认 hsbg/live/config.json）")
    p.add_argument("--set", dest="overrides", action="append", default=None,
                   metavar="KEY=VALUE",
                   help="覆盖配置，如 --set flow.max_games=5 "
                        "--set coords.points.end_turn=0.93,0.6（可多次）")
    p.add_argument("--games", type=int, default=None,
                   help="本局自动打多少局（默认取配置 flow.max_games；0=不限）")
    p.add_argument("--live", action="store_true",
                   help="真实点击（必须显式指定；需要游戏窗口）")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印计划，不发送真实输入（默认行为）")
    p.add_argument("--simulate", action="store_true",
                   help="dry-run 下用模拟状态走完整流程（无游戏/无日志也可演示）")
    p.add_argument("--blind", action="store_true",
                   help="不依赖日志/内存状态，按固定时间脚本盲操作")
    p.add_argument("--no-simulate", action="store_true",
                   help="日志不可用时不做模拟降级（只打印等待）")
    p.add_argument("--out-dir", default=None,
                   help="产物目录（默认 runs/live/<mode>_<时间戳>）")
    p.add_argument("--memory-reader", default=None, metavar="MODULE:FUNC",
                   help="内存状态读取入口（默认自动探测 tools.live_state_mem:read_live_state）")
    p.add_argument("--max-runtime", type=float, default=None,
                   help="最长运行秒数（默认取配置 flow.max_runtime_s）")
    p.add_argument("--realtime", action="store_true",
                   help="dry-run 也按真实节奏 sleep（默认 dry-run 加速执行）")
    p.add_argument("--dry-actions", type=int, default=None,
                   help="dry-run 最多执行多少计划动作后退出（0=不限；默认取配置）")
    p.add_argument("--dry-seconds", type=float, default=None,
                   help="dry-run 最长运行秒数后退出（0=不限；默认取配置）")
    p.add_argument("--window-title", action="append", default=None,
                   help="自定义窗口标题（可多次；默认 炉石传说/Hearthstone）")
    p.add_argument("--window-process", default=None,
                   help="自定义进程名（默认 Hearthstone.exe）")
    p.add_argument("--list-coords", action="store_true",
                   help="打印当前坐标配置（相对比例）后退出")
    p.add_argument("--show-config", action="store_true",
                   help="打印完整配置 JSON 后退出")
    p.add_argument("--capture", default=None, metavar="PATH",
                   help="真实截取游戏窗口到 PATH（需要窗口）")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet", action="store_true")
    return p


def _coord_table(config: LiveConfig) -> str:
    lines = ["== 坐标（窗口内相对比例 0–1）=="]
    lines.append("-- points --")
    for name, (x, y) in sorted(config.coords.points.items()):
        lines.append(f"{name:>20}: ({x:.4f}, {y:.4f})")
    for group, points in sorted(config.coords.groups.items()):
        lines.append(f"-- group {group} ({len(points)}) --")
        for i, (x, y) in enumerate(points):
            lines.append(f"  [{i}] ({x:.4f}, {y:.4f})")
    rect = config.window_rect
    lines.append(f"== window rect = {list(rect)} "
                 f"({rect[2] - rect[0]}x{rect[3] - rect[1]}) ==")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logger = (lambda msg: None) if args.quiet else (lambda msg: print(msg, flush=True))

    try:
        config = load_config(args.config, overrides=args.overrides)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[livebot] 配置错误: {exc}", file=sys.stderr)
        return 2
    if args.window_title:
        config.window.titles = list(args.window_title)
    if args.window_process:
        config.window.process = str(args.window_process)
    if args.max_runtime is not None:
        config.flow.max_runtime_s = float(args.max_runtime)
    if args.blind:
        config.flow.blind = True
    if args.no_simulate:
        config.flow.simulate_when_unavailable = False

    if args.list_coords:
        print(_coord_table(config))
        return 0
    if args.show_config:
        print(json.dumps(config.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.live and args.dry_run:
        print("[livebot] --live 与 --dry-run 不能同时使用", file=sys.stderr)
        return 2
    if args.live and args.simulate:
        print("[livebot] --simulate 只能用于 dry-run", file=sys.stderr)
        return 2
    play_live = bool(args.live)
    dry_run = not play_live

    # 窗口检查（live 必须有窗口；dry-run 不强制）
    if play_live:
        window = find_hearthstone_window(config)
        if window is None:
            print("[livebot] 找不到 Hearthstone 窗口：请先启动游戏，或改用 --dry-run",
                  file=sys.stderr)
            return 2
        logger(f"[livebot] 窗口: {window.title!r} {window.to_dict()['rect']} "
               f"({window.width}x{window.height})")
    else:
        window = None
        logger(f"[livebot] mode=DRY-RUN（真实点击请加 --live）"
               f"  config={args.config}")
        rect = config.window_rect
        logger(f"[livebot] 目标窗口 rect（预期）: {list(rect)}")

    if args.capture:
        if dry_run:
            print("[livebot] --capture 需要 --live（真实截图）", file=sys.stderr)
            return 2
        try:
            controller = InputController(
                config, dry_run=False, window=window, logger=logger,
            )
        except WindowNotFoundError as exc:
            print(f"[livebot] {exc}", file=sys.stderr)
            return 2
        path = controller.screenshot(Path(args.capture).name)
        controller.close()
        if path is None:
            print("[livebot] 截图失败（Pillow/权限问题）", file=sys.stderr)
            return 2
        logger(f"[livebot] 截图已保存: {path}")
        return 0

    watcher = None
    if args.simulate:
        games_for_sim = args.games if args.games is not None else config.flow.max_games
        watcher = SimulatedWatcher(config, games=max(1, int(games_for_sim or 1)))
        logger("[livebot] 使用 SimulatedWatcher（模拟状态，不读日志/不点真实输入）")

    sleep_fn = None
    if dry_run and not args.realtime:
        # dry-run 默认加速：不真实等待（计划中的 wait 由 controller 打印后跳过）
        sleep_fn = lambda _seconds: None  # noqa: E731

    # dry-run 预览保护：模拟模式跑完整流程，真实状态只预览有限动作/秒数
    dry_actions = (args.dry_actions if args.dry_actions is not None
                   else config.flow.dry_run_max_actions)
    dry_seconds = (args.dry_seconds if args.dry_seconds is not None
                   else config.flow.dry_run_max_seconds)
    if args.simulate:
        dry_actions, dry_seconds = 0, 0.0
    elif not play_live:
        if dry_seconds and dry_seconds <= 0:
            dry_seconds = 0.0
    if not dry_run:
        dry_actions, dry_seconds = 0, 0.0

    try:
        bot = LiveBot(
            config,
            live=play_live,
            watcher=watcher,
            memory_reader_spec=args.memory_reader,
            out_dir=Path(args.out_dir) if args.out_dir else None,
            sleep_fn=sleep_fn,
            logger=logger,
            verbose=args.verbose,
            dry_run_max_actions=dry_actions,
            dry_run_max_seconds=dry_seconds,
        )
    except WindowNotFoundError as exc:
        print(f"[livebot] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[livebot] 初始化失败: {exc}", file=sys.stderr)
        return 2

    summary = bot.run(max_games=args.games)
    if args.quiet:
        print(json.dumps(summary.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
