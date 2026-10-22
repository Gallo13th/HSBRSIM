"""`hsbg/live/config.json` 的加载/保存与坐标比例工具。

所有界面坐标都是 **窗口内相对比例**（0–1，左上角为原点），由
:class:`hsbg.live.wininput.InputController` 映射到屏幕像素。这样窗口移动/
换分辨率时只需改窗口 rect，配置不用变。

当前默认值
----------
* 窗口：1920×1080 屏幕、游戏窗口 rect ≈ ``(-7, 0, 1929, 1048)``（1936×1048，
  含标题栏；与 ``runs/live/game_screen.png`` 一致）。
* 主菜单「酒馆战棋」按钮：从 ``runs/live/game_screen.png`` 量得 ≈(0.485, 0.374)。
* 酒馆/商店/手牌/结束按钮：**固定比例初值**（尚未用真实酒馆截图校准），
  全部集中在 ``coords`` 里，可用 ``tools/livebot_calibrate.py`` 生成网格图后
  覆盖；也支持 ``--set coords.points.end_turn=0.93,0.60`` 之类命令行覆盖。

配置结构（JSON）::

    {
      "version": 1,
      "window":  {"titles": [...], "process": "Hearthstone.exe", "expected_rect": [l,t,r,b]},
      "paths":   {"power_log": "...", "hdt_log_dir": "...", "runs_dir": "runs/live"},
      "flow":    {"blind": false, "poll_interval_s": 0.25, "max_games": 5, ...},
      "delays":  {"after_click_s": 0.5, "drag_duration_s": 0.35, ...},
      "coords":  {"points": {"名字": [fx,fy], ...},
                  "groups": {"shop": [[fx,fy] x7], "hand": [...x10], ...}},
      "safety":  {"dry_run_default": true, "max_actions_per_turn": 40, ...}
    }
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 默认配置文件路径（与本模块同目录）
DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("config.json")

#: 窗口内相对坐标（0–1）
Point = Tuple[float, float]


def _default_shop() -> List[List[float]]:
    # 商店 7 格（动态布局的兜底）：实测间距 131px/1920=0.068229，y≈0.356
    return [[round(0.5 + (i - 3) * 0.068229, 4), 0.356] for i in range(7)]


def _default_board() -> List[List[float]]:
    # 己方棋盘 7 格（动态布局兜底）：同样的居中间距，落点 y≈0.552
    return [[round(0.5 + (i - 3) * 0.068229, 4), 0.552] for i in range(7)]


def _default_hand() -> List[List[float]]:
    # 手牌 10 格（兜底）：底部居中，间距 110px/1920≈0.0573
    return [[round(0.5 + (i - 4.5) * 0.057292, 4), 0.852] for i in range(10)]


def _default_hero_options() -> List[List[float]]:
    # 英雄选择：4 个候选卡中心（实机 2026-10-18：x=0.25/0.4115/0.5766/0.7344，y=0.436）
    xs = (0.2500, 0.4115, 0.5766, 0.7344)
    return [[x, 0.436] for x in xs]


def _default_choice_options() -> List[List[float]]:
    # 发现/三选一：实机截图（runs/live/calibrated_ingame.png）三张大卡中心
    return [[0.336, 0.41], [0.501, 0.41], [0.666, 0.41]]


@dataclass
class WindowConfig:
    """窗口查找与前台管理配置。"""

    titles: List[str] = field(default_factory=lambda: ["炉石传说", "Hearthstone"])
    process: str = "Hearthstone.exe"
    #: 找不到窗口时（dry-run / 校准）使用的窗口屏幕矩形 [left, top, right, bottom]
    expected_rect: List[int] = field(default_factory=lambda: [-7, 0, 1929, 1048])
    foreground_retries: int = 5
    restore_delay_s: float = 0.25
    #: True = 相对坐标按**客户区**（不含标题栏/边框）映射；False = 按窗口外框。
    #: 实机验证：游戏画面在客户区内，按外框映射会让底部手牌/结束按钮点偏。
    use_client_rect: bool = True


@dataclass
class PathsConfig:
    """日志与产物路径。"""

    power_log: str = r"C:\Program Files (x86)\Hearthstone\Logs\Power.log"
    #: HDT 日志目录（支持 %APPDATA% 展开）；同时会自动扫描常见安装位置
    hdt_log_dir: str = r"%APPDATA%\HearthstoneDeckTracker\Logs"
    runs_dir: str = "runs/live"
    #: Battle.net 启动器（客户端消失时用于 `--exec=launch WTCG` 重启游戏）
    battle_net: str = r"C:\Program Files (x86)\Battle.net\Battle.net.exe"


@dataclass
class FlowConfig:
    """对局循环节奏与停止条件。"""

    #: True = 只按固定时间/固定脚本盲操作（无日志/无内存状态时使用）
    blind: bool = False
    poll_interval_s: float = 0.25
    max_games: int = 5
    max_runtime_s: float = 7200.0
    #: 单局超时（超过视为异常，记录并回大厅）
    game_timeout_s: float = 2400.0
    #: 连续检测不到炉石进程/窗口多久后判定 client_gone（秒）
    client_gone_s: float = 20.0
    #: 客户端消失后是否自动用 Battle.net 重新启动
    restart_client: bool = True
    #: 重启后等待游戏窗口/内存就绪的最长时间（秒）
    restart_timeout_s: float = 180.0
    #: 结算界面重试次数上限（超过则记录 game_over_stuck 并停止该局）
    max_game_over_retries: int = 8
    #: 每局结束时把 Power.log 复制到会话目录（Power.log 每局会被截断/复用）
    archive_power_log: bool = True
    #: 战斗阶段至少等待时间（避免刚点完结束就误点）
    combat_wait_s: float = 40.0
    #: 招募阶段：点完一轮购买后的最短间隔，防止同一回合反复操作
    recruit_min_s: float = 1.0
    #: 每个 tick 最多执行的动作数（避免一次跑太多 UI 操作）
    max_actions_per_tick: int = 14
    #: 盲操作模式下一局预计时长（秒），到点后按 game_over 处理
    blind_game_duration_s: float = 900.0
    #: 盲操作模式每个"回合"的间隔（秒）
    blind_turn_s: float = 20.0
    # ── 招募阶段动作脚本（有内存状态时按实际 shop/hand 数量自动收紧）──
    #: 是否把商店随从全部拖走
    buy_all_shop: bool = True
    #: True = 先拖到手上（已实机验证），False = 直接拖到棋盘（未验证成功）
    buy_to_hand: bool = True
    #: 是否把手牌随从打到棋盘（已实机验证：(0.479,0.90)→(0.5,0.715)）
    play_hand_minions: bool = True
    #: 盲操作时每回合买几个 / 打几个
    buy_count: int = 7
    play_count: int = 7
    #: 是否点英雄技能
    use_hero_power: bool = False
    #: 英雄选择点第几个候选（0 起；锁住的候选点了没反应，planner 会自动重试下一个）
    hero_option_index: int = 0
    #: 结束回合用键盘还是点按钮（酒馆战棋单人模式没有结束回合按钮；仅特殊 UI 用）
    end_turn_use_key: bool = False
    #: 是否主动发送"结束回合"动作。False = 酒馆战棋单人模式的正确做法：
    #: 招募阶段由计时器自动结束（官方 UI 无结束回合按钮），planner 买/出牌后
    #: 只等待 phase 变化；"开始战斗"按钮只在计时结束后出现。
    send_end_turn: bool = False
    #: 结束回合快捷键（默认 E，炉石默认键位）
    end_turn_key: str = "E"
    #: 暂停热键（VK_F12 = 123）
    pause_vk: int = 123
    pause_poll_s: float = 0.1
    #: 是否在 dry-run 时使用模拟状态（无窗口/无日志环境演示用）
    simulate_when_unavailable: bool = True
    #: 内存状态读取最小间隔（秒；rea-operator 的 read_live_state 较重）
    memory_poll_s: float = 0.5
    #: dry-run 预览保护：最多执行多少个计划动作 / 最多跑多少秒后自动退出
    #: （0 = 不限制；CLI 的 --simulate/--realtime 会置 0）
    dry_run_max_actions: int = 40
    dry_run_max_seconds: float = 20.0


@dataclass
class DelaysConfig:
    """每类操作的节奏（秒）。"""

    after_click_s: float = 0.5
    after_drag_s: float = 0.35
    drag_duration_s: float = 0.35
    after_key_s: float = 0.3
    hero_select_wait_s: float = 1.5
    between_buys_s: float = 0.25
    end_turn_wait_s: float = 1.0
    choice_wait_s: float = 0.6
    menu_retry_s: float = 5.0
    after_game_wait_s: float = 8.0
    screenshot_settle_s: float = 0.2


@dataclass
class CoordsConfig:
    """窗口内相对坐标：命名点 + 序列组 + 动态布局参数。"""

    #: 单个点，name -> (fx, fy)
    points: Dict[str, List[float]] = field(default_factory=lambda: {
        # 主菜单 / 酒馆大厅（2026-10-18 实机校准，client 坐标）
        "menu_battlegrounds": [0.4995, 0.3922],  # 主菜单「酒馆战棋」
        "menu_back": [0.035, 0.035],             # 左上返回箭头（备用）
        "splash_click": [0.5000, 0.5000],        # 启动页「点击开始」/通用点击
        "lobby_play": [0.7172, 0.8028],          # 酒馆大厅「开始」圆钮中心
        "lobby_back": [0.7810, 0.9230],          # 大厅右下「返回」
        "lobby_play_again": [0.7172, 0.8028],    # 结算后回大厅再点「开始」
        # 对局结算界面：优先点「继续/返回」回大厅（16:9 实测 (960,850) 可退出结算）
        "result_continue": [0.5393, 0.8492],
        "result_continue2": [0.5000, 0.8600],
        "result_center": [0.5000, 0.5000],
        # 对局内（client 坐标；2026-10-18 实机验证）
        "end_turn": [0.7917, 0.4410],           # 右中「开始战斗/结束回合」按钮
        "hero_power": [0.5920, 0.7900],          # 底部圆钮（英雄技能/刷新，待微调）
        "hero_confirm": [0.5000, 0.7582],        # 英雄选择「确认」
        "choice_confirm": [0.5000, 0.7900],      # 三选一确认（待校准）
        "error_dismiss": [0.50, 0.85],           # 弹窗/错误确认
    })
    #: 序列组：name -> [[fx, fy], ...]（动态布局不可用时兜底）
    groups: Dict[str, List[List[float]]] = field(default_factory=lambda: {
        "shop": _default_shop(),                # 商店 7 格
        "board": _default_board(),              # 己方棋盘 7 格
        "hand": _default_hand(),                # 手牌 10 格
        "hero_options": _default_hero_options(),  # 英雄候选
        "choice_options": _default_choice_options(),  # 发现/三选一选项
    })
    #: 动态布局参数（BG 商店/棋盘/手牌随"当前格数"居中排布，按像素间距换算比例）
    layout: Dict[str, float] = field(default_factory=lambda: {
        # 实测：4 个 offer 时商店卡中心 image x=765/896/1027/1158，间距 131px（1920 宽）
        "shop_y": 0.356,          # 商店随从行 y
        "shop_spacing": 0.068229,  # 131 / 1920
        "board_y": 0.715,         # 拖到棋盘的落点 y（实测 (0.5,0.72) 成功出牌）
        "board_spacing": 0.068229,
        "hand_y": 0.900,          # 手牌卡可见部分 y（下缘被裁，抓上半部）
        "hand_spacing": 0.057292,  # 110 / 1920
        "hand_center_x": 0.480,   # 实测单张手牌中心 image x≈922
        "center_x": 0.5,
    })

    def point(self, name: str) -> Point:
        try:
            x, y = self.points[name]
        except KeyError as exc:
            raise KeyError(f"未配置坐标点 {name!r}；已有: {sorted(self.points)}") from exc
        return float(x), float(y)

    def group(self, name: str) -> List[Point]:
        try:
            raw = self.groups[name]
        except KeyError as exc:
            raise KeyError(f"未配置坐标组 {name!r}；已有: {sorted(self.groups)}") from exc
        return [(float(x), float(y)) for x, y in raw]

    def set_point(self, name: str, point: Sequence[float]) -> None:
        if len(point) != 2:
            raise ValueError(f"坐标必须是 [fx, fy]，得到 {point!r}")
        self.points[name] = [float(point[0]), float(point[1])]


@dataclass
class SafetyConfig:
    """安全阀：dry-run 默认、每回合动作上限、错误处理。"""

    dry_run_default: bool = True
    #: 没有显式 --live 时绝不真实点击（require_live_flag=False 时允许 live=True 构造）
    require_live_flag: bool = True
    max_actions_per_turn: int = 40
    max_consecutive_errors: int = 5
    screenshot_on_error: bool = True
    #: 是否允许把游戏窗口拉到前台（关掉则只在已是前台时点击）
    allow_focus_steal: bool = True
    #: 单个动作后等待 UI 稳定的最小时间（秒）
    min_action_interval_s: float = 0.15


@dataclass
class LiveConfig:
    """完整配置（窗口/路径/节奏/坐标/安全）。"""

    version: int = 1
    window: WindowConfig = field(default_factory=WindowConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)
    delays: DelaysConfig = field(default_factory=DelaysConfig)
    coords: CoordsConfig = field(default_factory=CoordsConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)

    # ── 序列化 ──
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "window": _dataclass_to_dict(self.window),
            "paths": _dataclass_to_dict(self.paths),
            "flow": _dataclass_to_dict(self.flow),
            "delays": _dataclass_to_dict(self.delays),
            "coords": {
                "points": {k: list(v) for k, v in self.coords.points.items()},
                "groups": {k: [list(p) for p in v]
                           for k, v in self.coords.groups.items()},
                "layout": {k: float(v) for k, v in self.coords.layout.items()},
            },
            "safety": _dataclass_to_dict(self.safety),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LiveConfig":
        defaults = cls()
        cfg = copy.deepcopy(defaults)
        if not isinstance(data, dict):
            raise ValueError(f"配置必须是 JSON object，得到 {type(data).__name__}")
        cfg.version = int(data.get("version", defaults.version))
        cfg.window = _merge_dataclass(WindowConfig, data.get("window"), defaults.window)
        cfg.paths = _merge_dataclass(PathsConfig, data.get("paths"), defaults.paths)
        cfg.flow = _merge_dataclass(FlowConfig, data.get("flow"), defaults.flow)
        cfg.delays = _merge_dataclass(DelaysConfig, data.get("delays"), defaults.delays)
        cfg.coords = _merge_coords(CoordsConfig, data.get("coords"), defaults.coords)
        cfg.safety = _merge_dataclass(SafetyConfig, data.get("safety"), defaults.safety)
        return cfg

    # ── 文件 ──
    @classmethod
    def load(cls, path: Optional[Path | str] = None) -> "LiveConfig":
        path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not path.exists():
            # 允许不存在时使用内置默认（并提示），便于首次运行
            cfg = cls()
            cfg.validate()
            return cfg
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = cls.from_dict(data)
        cfg.validate()
        return cfg

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    # ── 校验 / 便利属性 ──
    def validate(self) -> None:
        rect = list(self.window.expected_rect or [])
        if len(rect) != 4 or rect[2] <= rect[0] or rect[3] <= rect[1]:
            raise ValueError(f"window.expected_rect 必须是 [left,top,right,bottom]，得到 {rect!r}")
        if self.flow.max_games < 0:
            raise ValueError("flow.max_games 必须 >= 0")
        if self.flow.poll_interval_s <= 0:
            raise ValueError("flow.poll_interval_s 必须 > 0")
        for name, pt in self.coords.points.items():
            _check_fraction(name, pt)
        for name, pts in self.coords.groups.items():
            if not pts:
                raise ValueError(f"coords.groups[{name!r}] 不能为空")
            for i, pt in enumerate(pts):
                _check_fraction(f"{name}[{i}]", pt)

    @property
    def window_rect(self) -> Tuple[int, int, int, int]:
        l, t, r, b = self.window.expected_rect
        return int(l), int(t), int(r), int(b)

    #: ``paths.hdt_log_dir`` 展开环境变量后的路径
    def hdt_log_dir_resolved(self) -> Path:
        return Path(os.path.expandvars(self.paths.hdt_log_dir)).expanduser()

    def runs_dir_resolved(self) -> Path:
        from hsbg.paths import ROOT

        p = Path(self.paths.runs_dir)
        return p if p.is_absolute() else ROOT / p

    def power_log_path(self) -> Path:
        return Path(os.path.expandvars(self.paths.power_log)).expanduser()

    # ── 命令行覆盖：`--set flow.max_games=3 --set coords.points.end_turn=0.93,0.6` ──
    def apply_overrides(self, overrides: Iterable[str]) -> List[str]:
        applied: List[str] = []
        for item in overrides:
            if "=" not in item:
                raise ValueError(f"--set 需要 key=value 形式，得到 {item!r}")
            dotted, raw = item.split("=", 1)
            self._set_path(dotted.strip(), raw.strip())
            applied.append(item)
        self.validate()
        return applied

    def _set_path(self, dotted: str, raw: str) -> None:
        parts = [p for p in dotted.split(".") if p]
        if not parts:
            raise ValueError("空配置键")
        obj: Any = self
        for part in parts[:-1]:
            if part == "coords":
                obj = self.coords
            elif part in ("points", "groups") and obj is self.coords:
                obj = getattr(obj, part)
            elif hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                raise KeyError(f"未知配置路径 {dotted!r}（卡在 {part!r}）")
        key = parts[-1]
        if obj is self.coords:
            if key not in self.coords.points:
                raise KeyError(f"未知坐标点 {key!r}")
            self.coords.points[key] = _parse_point(raw)
        elif isinstance(obj, dict):
            if obj is self.coords.points:
                if key not in obj:
                    raise KeyError(f"未知坐标点 {key!r}")
                obj[key] = _parse_point(raw)
            elif obj is self.coords.groups and ";" in raw:
                obj[key] = [_parse_point(part) for part in raw.split(";")
                            if part.strip()]
            elif obj is self.coords.groups:
                obj[key] = [_parse_point(raw)]
            elif obj is self.coords.layout:
                if key not in obj:
                    raise KeyError(f"未知布局参数 {key!r}")
                obj[key] = float(raw)
            else:
                obj[key] = _parse_point(raw)
        elif hasattr(obj, key):
            current = getattr(obj, key)
            setattr(obj, key, _coerce(raw, current))
        else:
            raise KeyError(f"未知配置项 {dotted!r}")


# ══════════════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════════════


def _dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in obj.__dataclass_fields__:  # type: ignore[attr-defined]
        value = getattr(obj, name)
        out[name] = list(value) if isinstance(value, (list, tuple)) else value
    return out


def _merge_dataclass(cls: Any, data: Any, default: Any) -> Any:
    obj = copy.deepcopy(default)
    if data is None:
        return obj
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__} 必须是 JSON object")
    for key, value in data.items():
        if not hasattr(obj, key):
            continue  # 向前兼容：忽略未知字段
        current = getattr(obj, key)
        if isinstance(current, list) and isinstance(value, (list, tuple)):
            setattr(obj, key, list(value))
        elif isinstance(current, bool):
            setattr(obj, key, bool(value))
        elif isinstance(current, float):
            setattr(obj, key, float(value))
        elif isinstance(current, int):
            setattr(obj, key, int(value))
        elif isinstance(current, str):
            setattr(obj, key, str(value))
        else:  # pragma: no cover - 现有字段都属于上面的简单类型
            setattr(obj, key, value)
    return obj


def _merge_coords(cls: Any, data: Any, default: CoordsConfig) -> CoordsConfig:
    obj = CoordsConfig(
        points={k: list(v) for k, v in default.points.items()},
        groups={k: [list(p) for p in v] for k, v in default.groups.items()},
        layout={k: float(v) for k, v in default.layout.items()},
    )
    if data is None:
        return obj
    if not isinstance(data, dict):
        raise ValueError("coords 必须是 JSON object")
    for name, point in (data.get("points") or {}).items():
        obj.points[str(name)] = _parse_point(point)
    for name, pts in (data.get("groups") or {}).items():
        if not isinstance(pts, (list, tuple)):
            raise ValueError(f"coords.groups[{name!r}] 必须是点列表")
        obj.groups[str(name)] = [_parse_point(p) for p in pts]
    for name, value in (data.get("layout") or {}).items():
        obj.layout[str(name)] = float(value)
    return obj


def _parse_point(value: Any) -> List[float]:
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        if len(parts) != 2:
            raise ValueError(f"坐标字符串需要 'x,y'，得到 {value!r}")
        return [float(parts[0]), float(parts[1])]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"坐标需要 [fx, fy]，得到 {value!r}")
    return [float(value[0]), float(value[1])]


def _check_fraction(name: str, point: Sequence[float]) -> None:
    if len(point) != 2:
        raise ValueError(f"坐标 {name} 需要 2 个值，得到 {point!r}")
    x, y = float(point[0]), float(point[1])
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(f"坐标 {name}={point!r} 超出 [0,1] 相对比例范围")


def _coerce(raw: str, current: Any) -> Any:
    if isinstance(current, bool):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"布尔值解析失败: {raw!r}")
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, (list, tuple)):
        return [part.strip() for part in raw.split(",")]
    return raw


def load_config(
    path: Optional[Path | str] = None,
    overrides: Optional[Iterable[str]] = None,
) -> LiveConfig:
    """加载配置（不存在时用内置默认），并应用 ``--set`` 覆盖。"""
    cfg = LiveConfig.load(path)
    if overrides:
        cfg.apply_overrides(overrides)
    return cfg


def save_config(cfg: LiveConfig, path: Path | str) -> Path:
    """保存配置（默认路径可用 :data:`DEFAULT_CONFIG_PATH`）。"""
    return cfg.save(path)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "Point",
    "WindowConfig",
    "PathsConfig",
    "FlowConfig",
    "DelaysConfig",
    "CoordsConfig",
    "SafetyConfig",
    "LiveConfig",
    "load_config",
    "save_config",
]
