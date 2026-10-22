#!/usr/bin/env python
"""坐标校准工具：截图 + 画网格 + 标出配置里的按钮/槽位。

用法::

    # 用已有截图（无需游戏窗口）：生成带网格与标注的图
    python tools/livebot_calibrate.py --image runs/live/game_screen.png

    # 真实截取当前游戏窗口（需要游戏已启动）
    python tools/livebot_calibrate.py --capture

    # 修改窗口 rect / 网格步长 / 输出路径
    python tools/livebot_calibrate.py --image runs/live/game_screen.png \
        --rect -7,0,1929,1048 --grid 0.05 --out runs/live/calibrated.png

输出的 PNG 上：
* 浅色网格 = 每 ``--grid`` 比例；
* 顶部/左侧标注 0.0–1.0 比例；
* 圆形 = ``coords.points`` 里的命名按钮；
* 方框 + 编号 = ``coords.groups`` 里的槽位序列（shop/board/hand/...）。
按图调整 ``hsbg/live/config.json``（或 ``--set coords.points.xxx=fx,fy``）即可。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from hsbg.live.config import DEFAULT_CONFIG_PATH, LiveConfig, load_config  # noqa: E402


def _parse_rect(text: str) -> Tuple[int, int, int, int]:
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect 需要 left,top,right,bottom")
    return tuple(int(float(p)) for p in parts)  # type: ignore[return-value]


def _load_image(path: Path):
    from PIL import Image

    return Image.open(path).convert("RGB")


def _capture_window(
    config: LiveConfig,
) -> Optional[Tuple[Path, "object", Tuple[int, int, int, int]]]:
    """真实截图（需要游戏窗口）；返回 (路径, 图像, 客户区屏幕 rect)。"""
    try:
        from hsbg.live.wininput import InputController, WindowNotFoundError
    except Exception as exc:  # noqa: BLE001
        print(f"[calibrate] 无法导入 wininput: {exc}", file=sys.stderr)
        return None
    try:
        controller = InputController(config, dry_run=False, logger=print)
    except WindowNotFoundError as exc:
        print(f"[calibrate] {exc}", file=sys.stderr)
        return None
    rect = controller.mapping_rect
    path = controller.screenshot("calibrate_capture.png")
    controller.close()
    if path is None:
        print("[calibrate] 截图失败（Pillow 缺失或权限问题）", file=sys.stderr)
        return None
    return path, _load_image(path), rect


def _draw_annotations(
    image,
    config: LiveConfig,
    *,
    grid: float,
    rect: Tuple[int, int, int, int],
    show_groups: bool = True,
) -> "object":
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    # ── 网格 ──
    if grid > 0:
        steps = max(1, int(round(1.0 / grid)))
        for i in range(steps + 1):
            frac = i / steps
            x = int(frac * (width - 1))
            y = int(frac * (height - 1))
            draw.line([(x, 0), (x, height)], fill=(255, 255, 255, 60), width=1)
            draw.line([(0, y), (width, y)], fill=(255, 255, 255, 60), width=1)
            if i % max(1, int(round(0.1 / grid))) == 0:
                draw.text((x + 2, 2), f"{frac:.2f}", fill=(255, 255, 0, 220))
                draw.text((2, y + 1), f"{frac:.2f}", fill=(255, 255, 0, 220))

    def to_px(fx: float, fy: float) -> Tuple[int, int]:
        return int(fx * (width - 1)), int(fy * (height - 1))

    # ── 命名点 ──
    for name, (fx, fy) in sorted(config.coords.points.items()):
        x, y = to_px(fx, fy)
        r = 7
        draw.ellipse([(x - r, y - r), (x + r, y + r)],
                     outline=(255, 64, 64, 255), width=2)
        draw.line([(x - r - 4, y), (x + r + 4, y)], fill=(255, 64, 64, 255))
        draw.line([(x, y - r - 4), (x, y + r + 4)], fill=(255, 64, 64, 255))
        draw.text((x + r + 3, y - r - 6), f"{name} ({fx:.3f},{fy:.3f})",
                  fill=(255, 220, 64, 255))

    # ── 槽位组 ──
    if show_groups:
        colors = {
            "shop": (64, 200, 255),
            "board": (120, 255, 120),
            "hand": (255, 160, 64),
            "hero_options": (255, 64, 255),
            "choice_options": (64, 255, 200),
        }
        for group, points in sorted(config.coords.groups.items()):
            color = colors.get(group, (200, 200, 200))
            for i, (fx, fy) in enumerate(points):
                x, y = to_px(fx, fy)
                half = 18
                draw.rectangle([(x - half, y - half), (x + half, y + half)],
                               outline=(*color, 255), width=2)
                draw.text((x - half + 2, y - half + 1), f"{i}",
                          fill=(*color, 255))
            if points:
                fx0, fy0 = points[0]
                draw.text((to_px(fx0, fy0)[0] - 18, to_px(fx0, fy0)[1] - 34),
                          group, fill=(*color, 255))

    # ── 窗口 rect 信息 ──
    info = (f"rect={list(rect)} image={width}x{height} grid={grid}")
    draw.rectangle([(0, height - 16), (width - 1, height - 1)],
                   fill=(0, 0, 0, 160))
    draw.text((4, height - 14), info, fill=(255, 255, 255, 255))
    return image


def _print_table(config: LiveConfig, image_size: Tuple[int, int],
                 rect: Tuple[int, int, int, int]) -> None:
    width, height = image_size
    rw = max(1, rect[2] - rect[0])
    rh = max(1, rect[3] - rect[1])
    rows: List[str] = []
    rows.append(f"== 坐标表（窗口 rect={list(rect)}，截图 {width}x{height}）==")
    rows.append(f"{'name':>20}  {'frac':>16}  {'image px':>14}  {'screen px':>14}")
    for name, (fx, fy) in sorted(config.coords.points.items()):
        rows.append(
            f"{name:>20}  ({fx:.4f},{fy:.4f})  "
            f"({int(fx * (width - 1)):>5},{int(fy * (height - 1)):>5})  "
            f"({rect[0] + int(fx * rw):>5},{rect[1] + int(fy * rh):>5})"
        )
    for group, points in sorted(config.coords.groups.items()):
        rows.append(f"-- group {group} ({len(points)}) --")
        for i, (fx, fy) in enumerate(points):
            rows.append(
                f"{f'{group}[{i}]':>20}  ({fx:.4f},{fy:.4f})  "
                f"({int(fx * (width - 1)):>5},{int(fy * (height - 1)):>5})  "
                f"({rect[0] + int(fx * rw):>5},{rect[1] + int(fy * rh):>5})"
            )
    print("\n".join(rows))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="截图 + 网格 + 标注坐标（校准 hsbg/live/config.json）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    p.add_argument("--image", default=None,
                   help="已有截图路径（不给则尝试 --capture 真实截图）")
    p.add_argument("--capture", action="store_true",
                   help="真实截取游戏窗口（需要游戏窗口；默认输出 runs/live/）")
    p.add_argument("--rect", type=_parse_rect, default=None,
                   help="窗口屏幕矩形 left,top,right,bottom（默认取配置）")
    p.add_argument("--grid", type=float, default=0.05, help="网格步长（比例）")
    p.add_argument("--out", default="runs/live/calibrated.png",
                   help="标注图输出路径")
    p.add_argument("--no-groups", action="store_true", help="不画槽位组框")
    p.add_argument("--json", action="store_true", help="同时打印 JSON 坐标表")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_config(args.config)
    rect: Optional[Tuple[int, int, int, int]] = args.rect

    image = None
    if args.image:
        path = Path(args.image)
        if not path.exists():
            print(f"[calibrate] 截图不存在: {path}", file=sys.stderr)
            return 2
        image = _load_image(path)
        print(f"[calibrate] 使用截图: {path}")
        if rect is None:
            # 离线截图默认视作客户区：屏幕坐标 = 图像像素（左上 0,0）
            rect = (0, 0, int(image.size[0]), int(image.size[1]))
    else:
        captured = _capture_window(config)
        if captured is None:
            print("[calibrate] 无截图可用：请用 --image 指定已有截图，或启动游戏后用 "
                  "--capture", file=sys.stderr)
            return 2
        path, image, captured_rect = captured
        if rect is None:
            rect = captured_rect
        print(f"[calibrate] 已截图: {path}  客户区 rect={list(rect)}")
    assert rect is not None

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    annotated = _draw_annotations(image, config, grid=float(args.grid),
                                  rect=rect, show_groups=not args.no_groups)
    annotated.save(out)
    print(f"[calibrate] 标注图已保存: {out}")

    _print_table(config, image.size, rect)
    if args.json:
        payload = {
            "rect": list(rect),
            "image_size": list(image.size),
            "points": {k: list(v) for k, v in config.coords.points.items()},
            "groups": {k: [list(p) for p in v]
                       for k, v in config.coords.groups.items()},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
