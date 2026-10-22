"""``hsbg/live`` 自动化代打测试（不发送真实输入、不读真实游戏）。

覆盖：配置/坐标映射/暂停热键/日志 watcher/planner 状态机/dry-run 主循环/
CLI/校准工具/与 rea-operator 模块（bridge live_log、live_state_mem）的适配。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from hsbg.live.config import (
    DEFAULT_CONFIG_PATH,
    LiveConfig,
    load_config,
)
from hsbg.live.logwatch import (
    PHASE_CHOICE,
    PHASE_COMBAT,
    PHASE_GAME_OVER,
    PHASE_HERO_SELECT,
    PHASE_LOBBY,
    PHASE_MENU,
    PHASE_RECRUIT,
    ExternalWatcherAdapter,
    LiveLogWatcher,
    LiveSnapshot,
    create_watcher,
)
from hsbg.live.memory_state import apply_memory, load_memory_reader
from hsbg.live.planner import PlannedAction, Planner
from hsbg.live.runner import LiveBot, SimulatedWatcher
from hsbg.live.wininput import (
    VK_CODES,
    DryRunBackend,
    InputController,
    PauseController,
    WindowInfo,
)

ROOT = Path(__file__).resolve().parent.parent
RECT = (-7, 0, 1929, 1048)


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def _load_script(relpath: str, name: str):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


def _config(tmp_path: Path, **overrides) -> LiveConfig:
    """测试配置：短循环、关闭自动模拟/真实路径依赖。"""
    cfg = LiveConfig()
    cfg.paths.runs_dir = str(tmp_path / "runs")
    cfg.paths.power_log = str(tmp_path / "no_such_power.log")
    cfg.paths.hdt_log_dir = str(tmp_path / "no_such_hdt")
    cfg.flow.poll_interval_s = 0.001
    cfg.flow.max_runtime_s = 120.0
    cfg.flow.max_games = 3
    cfg.flow.simulate_when_unavailable = False
    cfg.flow.memory_poll_s = 0.001
    cfg.safety.max_consecutive_errors = 3
    for key, value in overrides.items():
        setattr(cfg.flow, key, value)
    return cfg


def _snap(phase: str, *, turn: int = 0, game: int = 1, in_game: bool = True,
          **kwargs) -> LiveSnapshot:
    return LiveSnapshot(phase=phase, turn=turn, game_id=game,
                        in_game=in_game, source="test", **kwargs)


def _write_lines(path: Path, lines: list[str], mode: str = "a") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in
            Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════


def test_config_default_and_roundtrip(tmp_path: Path) -> None:
    assert DEFAULT_CONFIG_PATH.exists()
    cfg = load_config(DEFAULT_CONFIG_PATH)
    assert cfg.window_rect == RECT
    assert len(cfg.coords.group("shop")) == 7
    assert len(cfg.coords.group("hand")) == 10
    assert len(cfg.coords.group("board")) == 7
    assert len(cfg.coords.group("hero_options")) >= 2
    cfg.flow.max_games = 2
    out = tmp_path / "cfg.json"
    cfg.save(out)
    loaded = load_config(out)
    assert loaded.to_dict() == cfg.to_dict()


def test_config_overrides() -> None:
    cfg = LiveConfig()
    applied = cfg.apply_overrides([
        "flow.max_games=2",
        "coords.points.end_turn=0.93,0.61",
        "coords.groups.shop=0.1,0.6;0.2,0.6",
    ])
    assert len(applied) == 3
    assert cfg.flow.max_games == 2
    assert cfg.coords.point("end_turn") == (0.93, 0.61)
    assert len(cfg.coords.group("shop")) == 2
    with pytest.raises((ValueError, KeyError)):
        cfg.apply_overrides(["coords.points.unknown_point=0.1,0.1"])
    with pytest.raises(ValueError):
        cfg.apply_overrides(["coords.points.end_turn=1.5,0.1"])


# ══════════════════════════════════════════════════════════════════════
# 输入层（dry-run backend）
# ══════════════════════════════════════════════════════════════════════


def test_fraction_to_screen_mapping(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    window = WindowInfo(hwnd=0, title="mock", process="mock", rect=RECT)
    backend = DryRunBackend(window=window, screen_size=(4000, 3000))
    ctl = InputController(cfg, backend=backend, window=window, dry_run=True)
    # 相对比例 → 窗口 rect 内像素（clamp 到屏幕 [0, screen-1]；
    # 本用例把屏幕设大以验证 rect 映射本身）
    assert ctl.frac_to_screen(0.0, 0.0) == (0, 0)  # -7 被 clamp
    assert ctl.frac_to_screen(0.5, 0.5) == (961, 524)
    assert ctl.frac_to_screen(0.5, 0.0) == (961, 0)
    assert ctl.frac_to_screen(0.0, 0.5) == (0, 524)
    # 点击/拖拽/按键/等待都记录到 ops，且 dry-run 不调用底层输入
    ctl.click(0.5, 0.5, note="test")
    ctl.drag((0.15, 0.60), (0.28, 0.87), note="shop->hand")
    ctl.key("E")
    ctl.wait(0.0)
    kinds = [op["kind"] for op in ctl.ops]
    assert kinds == ["click", "drag", "key", "wait"]
    assert ctl.ops[0]["x"] == 961 and ctl.ops[0]["y"] == 524
    assert not any(name == "click" for name, _args in backend.calls)
    assert not any(name == "key" for name, _args in backend.calls)
    ctl.close()


def test_fraction_mapping_custom_rect(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    window = WindowInfo(hwnd=1, title="x", process="x", rect=(100, 50, 1100, 850))
    ctl = InputController(cfg, backend=DryRunBackend(window),
                          window=window, dry_run=True)
    assert ctl.frac_to_screen(0.0, 0.0) == (100, 50)
    assert ctl.frac_to_screen(0.5, 0.5) == (600, 450)
    assert ctl.frac_to_screen(1.0, 1.0) == (1100, 850)
    ctl.close()


def test_client_rect_mapping_preferred(tmp_path: Path) -> None:
    """默认按客户区映射（窗口外框与客户区不同时以客户区为准）。"""
    cfg = _config(tmp_path)
    window = WindowInfo(
        hwnd=2, title="x", process="x",
        rect=(-7, 0, 1929, 1048),
        client_rect=(1, 31, 1921, 1041),  # 去边框/标题栏后的游戏画面
    )
    ctl = InputController(cfg, backend=DryRunBackend(window, screen_size=(4000, 3000)),
                          window=window, dry_run=True)
    assert ctl.mapping_rect == (1, 31, 1921, 1041)
    assert ctl.frac_to_screen(0.0, 0.0) == (1, 31)
    assert ctl.frac_to_screen(1.0, 1.0) == (1921, 1041)
    assert ctl.frac_to_screen(0.5, 0.5) == (961, 536)
    ctl.close()
    # 可切回窗口外框映射
    cfg.window.use_client_rect = False
    ctl = InputController(cfg, backend=DryRunBackend(window, screen_size=(4000, 3000)),
                          window=window, dry_run=True)
    assert ctl.mapping_rect == (-7, 0, 1929, 1048)
    assert ctl.frac_to_screen(0.5, 0.5) == (961, 524)
    ctl.close()


def test_pause_controller_toggle() -> None:
    down = {"v": 0}
    pause = PauseController(lambda vk: bool(down["v"]),
                            vk=VK_CODES["F12"])
    assert pause.poll_once() is False  # 未按下
    down["v"] = 1
    assert pause.poll_once() is True   # 按下沿 → 暂停
    assert pause.poll_once() is True   # 长按不重复 toggle
    down["v"] = 0
    assert pause.poll_once() is True   # 抬起
    down["v"] = 1
    assert pause.poll_once() is False  # 再按 → 恢复
    pause.set_paused(True)
    assert pause.paused is True
    pause.set_paused(False)
    assert pause.paused is False


def test_win32_backend_basic_no_input() -> None:
    """真实 Win32 后端只做无副作用检查（屏幕尺寸/热键状态/窗口枚举，不发输入）。"""
    if sys.platform != "win32":
        pytest.skip("Win32Backend 仅 Windows")
    from hsbg.live.wininput import Win32Backend

    backend = Win32Backend()
    width, height = backend.screen_size()
    assert width > 0 and height > 0
    assert isinstance(backend.is_key_down(VK_CODES["F12"]), bool)
    window = backend.find_window(["炉石传说", "Hearthstone"], "Hearthstone.exe")
    if window is not None:
        assert window.width > 0 and window.height > 0


# ══════════════════════════════════════════════════════════════════════
# 日志 watcher
# ══════════════════════════════════════════════════════════════════════


def test_power_log_watcher_lifecycle(tmp_path: Path) -> None:
    power = tmp_path / "Power.log"
    hdt_dir = tmp_path / "hdt"
    hdt_dir.mkdir()

    def line(text: str) -> str:
        return f"D 21:16:02.5176110 {text}"

    _write_lines(power, [
        line("GameState.DebugPrintPower() - CREATE_GAME"),
        line("GameState.DebugPrintGame() - GameType=GT_BATTLEGROUNDS"),
        line("GameState.DebugPrintPower() -     Player EntityID=8 PlayerID=3 "
             "GameAccountId=[hi=144115211015832391 lo=81501831]"),
        line("GameState.DebugPrintPower() -         tag=HERO_ENTITY value=29"),
    ], mode="w")
    watcher = LiveLogWatcher(power_log_path=power, hdt_log_dir=hdt_dir,
                             start_at_end=False)
    snap = watcher.poll()
    assert snap.in_game is True
    assert snap.phase == PHASE_HERO_SELECT
    assert snap.game_id == 1

    _write_lines(power, [
        line("GameState.DebugPrintPower() -     TAG_CHANGE Entity=GameEntity "
             "tag=TURN value=1"),
        line("GameState.DebugPrintOptions() - id=1"),
        line("GameState.DebugPrintOptions() -   option 0 type=END_TURN "
             "mainEntity= error=INVALID errorParam="),
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_RECRUIT
    assert snap.turn == 1

    _write_lines(power, [
        line("GameState.DebugPrintEntityChoices() - id=1 Player=p "
             "TaskList=7 ChoiceType=DISCOVER CountMin=1 CountMax=1"),
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_CHOICE
    assert snap.choice_active is True

    _write_lines(power, [
        line("GameState.DebugPrintPower() -     TAG_CHANGE Entity=GameEntity "
             "tag=STEP value=MAIN_END"),
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_COMBAT

    _write_lines(power, [
        line("GameState.DebugPrintPower() -     TAG_CHANGE Entity=GameEntity "
             "tag=STEP value=MAIN_READY"),
        line("GameState.DebugPrintPower() -     TAG_CHANGE Entity=GameEntity "
             "tag=TURN value=2"),
    ])
    snap = watcher.poll()
    assert snap.phase in (PHASE_RECRUIT,)
    assert snap.turn == 2

    _write_lines(power, [
        line("GameState.DebugPrintPower() -     TAG_CHANGE Entity=29 "
             "tag=PLAYSTATE value=DEAD"),
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_GAME_OVER
    assert snap.in_game is False
    assert watcher.game_history, "应记录对局历史"
    assert watcher.game_history[-1]["game_id"] == 1


def test_hdt_log_watcher_phases(tmp_path: Path) -> None:
    hdt_dir = tmp_path / "hdt"
    hdt_dir.mkdir()
    hdt = hdt_dir / "hdt_log.txt"
    _write_lines(hdt, [
        "22:14:45|Info|GameV2.CurrentMode >> BACON",
    ], mode="w")
    watcher = LiveLogWatcher(power_log_path=tmp_path / "nope.log",
                             hdt_log_dir=hdt_dir, start_at_end=False)
    snap = watcher.poll()
    assert snap.phase == PHASE_LOBBY

    _write_lines(hdt, [
        "22:15:03|Info|GameEventHandler.HandleGameStart >> --- Game start ---",
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_HERO_SELECT
    assert snap.in_game is True
    assert snap.game_id == 1

    _write_lines(hdt, [
        "22:15:39|Info|GameEventHandler.HandleTurnStart >> --- Player turn 1 ---",
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_RECRUIT
    assert snap.turn == 1

    _write_lines(hdt, [
        "22:16:22|Info|BobsBuddyInvoker.StartCombat >> abc_2",
        "22:16:23|Info|BobsBuddyInvoker.StartCombat >> Setting UI state to combat...",
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_COMBAT

    _write_lines(hdt, [
        "22:16:34|Info|BobsBuddyInvoker.StartShoppingAsync >> abc_2",
        "22:16:34|Info|BobsBuddyInvoker.StartShoppingAsync >> Setting UI state to Shopping",
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_RECRUIT
    assert snap.turn == 2

    _write_lines(hdt, [
        "22:32:11|Info|GameEventHandler.HandleLoss >> --- Game was lost! ---",
        "22:32:11|Info|GameStats.GameEnd >> Current Game ended after 10 turns",
        "22:32:11|Info|GameEventHandler.HandleGameEnd >> Game ended...",
    ])
    snap = watcher.poll()
    assert snap.phase == PHASE_GAME_OVER
    assert snap.in_game is False
    assert snap.turns_played == 10
    assert watcher.game_history
    assert watcher.game_history[-1]["turns"] == 10


def test_watcher_missing_files_no_crash(tmp_path: Path) -> None:
    watcher = LiveLogWatcher(power_log_path=tmp_path / "none.log",
                             hdt_log_dir=tmp_path / "none_dir",
                             start_at_end=False)
    snap = watcher.poll()
    assert isinstance(snap, LiveSnapshot)
    assert watcher.has_sources is False
    assert watcher.snapshot().phase in (PHASE_MENU, "unknown")


def test_hdt_observer_mode_and_phase(tmp_path: Path) -> None:
    from hsbg.live.logwatch import _HdtObserver

    hdt_dir = tmp_path / "hdt"
    hdt_dir.mkdir()
    hdt = hdt_dir / "hdt_log.txt"
    _write_lines(hdt, ["22:14:45|Info|GameV2.CurrentMode >> BACON"], mode="w")
    obs = _HdtObserver(hdt_dir)
    obs.poll()
    assert obs.mode == "BACON"
    assert obs.phase == PHASE_LOBBY and obs.in_game is False

    _write_lines(hdt, [
        "22:15:03|Info|GameEventHandler.HandleGameStart >> --- Game start ---",
        "22:15:39|Info|GameEventHandler.HandleTurnStart >> --- Player turn 1 ---",
    ])
    obs.poll()
    assert obs.in_game is True
    assert obs.phase == PHASE_RECRUIT and obs.turn == 1

    _write_lines(hdt, [
        "22:32:11|Info|GameEventHandler.HandleGameEnd >> Game ended...",
    ])
    obs.poll()
    assert obs.phase == PHASE_GAME_OVER and obs.in_game is False

    _write_lines(hdt, ["22:33:00|Info|GameV2.CurrentMode >> HUB"])
    obs.poll()
    assert obs.mode == "HUB" and obs.phase == PHASE_MENU


def test_memory_phase_alias_and_lobby_preserved(tmp_path: Path) -> None:
    # 内存 'hero' → hero_select
    merged = apply_memory(_snap(PHASE_HERO_SELECT), {"phase": "hero",
                                                     "attached": True})
    assert merged.phase == PHASE_HERO_SELECT and merged.in_game is True
    # 内存只知道 no_active_game，但 HDT 已判定酒馆大厅 → 保留 lobby（要点「开始」）
    merged = apply_memory(_snap(PHASE_LOBBY, in_game=False),
                          {"phase": "no_active_game", "attached": True})
    assert merged.phase == PHASE_LOBBY
    assert merged.in_game is False


def test_memory_placement_from_alive_count() -> None:
    # 死亡时仍有 7 人存活 → 第 8 名（内存 schema 没有直接 placement）
    merged = apply_memory(_snap(PHASE_GAME_OVER, in_game=False),
                          {"phase": "game_over", "attached": True,
                           "alive": False, "alive_count": 7})
    assert merged.placement == 8
    # 吃鸡：存活且只剩 1 人
    merged = apply_memory(_snap(PHASE_GAME_OVER, in_game=False),
                          {"phase": "game_over", "attached": True,
                           "alive": True, "alive_count": 1})
    assert merged.placement == 1


# ══════════════════════════════════════════════════════════════════════
# rea-operator 模块适配（bridge live_log / memory state）
# ══════════════════════════════════════════════════════════════════════


def test_bridge_snapshot_normalization() -> None:
    raw = {
        "log_path": "C:/x/Power.log", "attached": True, "offset": 123,
        "session_id": "sess", "game_active": True, "game_over_sent": False,
        "turn": 5, "phase": "recruit", "pending_choice_window": False,
        "gold": 7, "tier": 4, "hero_health": 22, "local_player_id": 3,
        "parser": {"phase": "recruit", "turn": 5},
    }
    snap = ExternalWatcherAdapter._normalize(raw)
    assert snap.phase == PHASE_RECRUIT
    assert snap.turn == 5 and snap.in_game is True
    assert snap.session_id == "sess"
    assert snap.power_log_path.endswith("Power.log")
    assert snap.notes["gold"] == 7

    raw["pending_choice_window"] = True
    assert ExternalWatcherAdapter._normalize(raw).phase == PHASE_CHOICE
    raw["pending_choice_window"] = False
    raw["game_over_sent"] = True
    assert ExternalWatcherAdapter._normalize(raw).phase == PHASE_GAME_OVER


def test_adapter_uses_hdt_for_lobby(tmp_path: Path) -> None:
    """bridge watcher 只报 game_active=False 时，用 HDT 的 BACON 判定为酒馆大厅。"""
    from hsbg.live.logwatch import ExternalWatcherAdapter

    cfg = _config(tmp_path)
    hdt_dir = tmp_path / "hdt_live"
    hdt_dir.mkdir()
    _write_lines(hdt_dir / "hdt_log.txt",
                 ["22:14:45|Info|GameV2.CurrentMode >> BACON"], mode="w")
    cfg.paths.hdt_log_dir = str(hdt_dir)

    class FakeImpl:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def poll(self):
            return []

        def snapshot(self):
            return {"game_active": False, "phase": "", "game_over_sent": False,
                    "turn": 0, "log_path": None, "offset": 0, "session_id": "",
                    "pending_choice_window": False}

    adapter = ExternalWatcherAdapter(FakeImpl, cfg)
    snap = adapter.poll()
    assert snap.phase == PHASE_LOBBY
    assert snap.in_game is False
    assert snap.mode == "BACON"
    assert snap.hdt_log_path.endswith("hdt_log.txt")


def test_create_watcher_returns_usable_object() -> None:
    cfg = LiveConfig()
    watcher = create_watcher(cfg, start_at_end=True)
    snap = watcher.poll()
    assert isinstance(snap, LiveSnapshot)
    # 属性/方法契约
    assert hasattr(watcher, "snapshot")
    assert hasattr(watcher, "has_sources")


def test_memory_state_apply(tmp_path: Path) -> None:
    base = _snap(PHASE_RECRUIT, turn=2, game=5)
    memory = {
        "schema": "hsbg.live_state.v1", "attached": True,
        "phase": "combat", "turn": 3,
        "shop": [{"card_id": "A"}, {"card_id": "B"}],
        "hand": [], "board": [{"card_id": "C"}],
        "gold": 6, "tier": 3, "health": 25,
    }
    merged = apply_memory(base, memory)
    assert merged.phase == PHASE_COMBAT
    assert merged.turn == 3
    assert merged.game_id == 5
    assert merged.in_game is True
    assert len(merged.notes["shop"]) == 2
    assert merged.notes["gold"] == 6

    # 无活动对局 → menu
    merged = apply_memory(base, {"phase": "no_active_game", "attached": True})
    assert merged.phase == PHASE_MENU
    assert merged.in_game is False
    # 内存不可用 → 不覆盖日志状态
    merged = apply_memory(base, {"phase": "unavailable", "attached": False})
    assert merged.phase == base.phase
    # choices 非空 → 进入 choice
    merged = apply_memory(base, {"phase": "recruit", "attached": True,
                                 "choices": [{"kind": "hero"}]})
    assert merged.phase == PHASE_CHOICE
    assert merged.choice_active is True
    # placement 显式给出
    merged = apply_memory(base, {"phase": "game_over", "attached": True,
                                 "placement": 3})
    assert merged.placement == 3


def test_memory_reader_optional() -> None:
    reader = load_memory_reader()
    if reader is None:
        pytest.skip("rea-operator 的 tools/live_state_mem 未就绪")
    try:
        state = reader()
    except OSError as exc:  # 无 Hearthstone 进程时读取器允许抛错（可选依赖）
        pytest.skip(f"无 Hearthstone 进程: {exc}")
    assert state is None or isinstance(state, dict)


# ══════════════════════════════════════════════════════════════════════
# Planner 状态机
# ══════════════════════════════════════════════════════════════════════


def test_planner_menu_lobby_hero(tmp_path: Path) -> None:
    clock = FakeClock()
    planner = Planner(_config(tmp_path), clock=clock)
    actions = planner.plan(_snap(PHASE_MENU, in_game=False))
    assert [a.kind for a in actions] == ["click"]
    assert actions[0].name == "menu_battlegrounds"
    assert planner.plan(_snap(PHASE_MENU, in_game=False)) == []  # 速率限制

    actions = planner.plan(_snap(PHASE_LOBBY, in_game=False))
    assert actions[0].name == "lobby_play"

    actions = planner.plan(_snap(PHASE_HERO_SELECT))
    assert [a.kind for a in actions] == ["click", "wait", "click", "wait"]
    assert actions[0].name == "hero_option_0"
    assert actions[2].name == "hero_confirm"
    # 同一局不再重复点
    assert planner.plan(_snap(PHASE_HERO_SELECT)) == []
    # 8s 后重试换下一个英雄候选
    clock.advance(9.0)
    retry = planner.plan(_snap(PHASE_HERO_SELECT))
    assert retry and retry[0].name == "hero_option_1"


def test_planner_recruit_sequence(tmp_path: Path) -> None:
    # 默认（单人 BG）：不主动结束回合，等待计时器；最后一步应是 wait_turn_timer
    planner = Planner(_config(tmp_path), clock=FakeClock())
    snap = _snap(PHASE_RECRUIT, turn=1)
    collected: list[PlannedAction] = []
    for _ in range(20):
        chunk = planner.plan(snap)
        if not chunk:
            break
        collected.extend(chunk)
    assert collected, "招募阶段应产出动作"
    assert len(collected) <= planner.config.safety.max_actions_per_turn
    kinds = [a.kind for a in collected]
    assert "drag" in kinds
    assert not [a for a in collected if a.name == "end_turn"]
    assert [a for a in collected if a.name == "wait_turn_timer"]
    # 脚本执行完 → 同一回合没有新动作（等待计时器/下一回合）
    assert planner.plan(snap) == []
    # 下一回合重新生成
    actions = planner.plan(_snap(PHASE_RECRUIT, turn=2))
    assert actions
    # 战斗/结算不操作
    assert planner.plan(_snap(PHASE_COMBAT, turn=2)) == []
    planner.plan(_snap(PHASE_GAME_OVER, turn=6))


def test_planner_send_end_turn_when_enabled(tmp_path: Path) -> None:
    """显式开启 send_end_turn（如 Duos/特殊 UI）时才发结束回合动作。"""
    planner = Planner(_config(tmp_path, send_end_turn=True,
                              end_turn_use_key=False), clock=FakeClock())
    snap = _snap(PHASE_RECRUIT, turn=1)
    collected: list[PlannedAction] = []
    for _ in range(20):
        chunk = planner.plan(snap)
        if not chunk:
            break
        collected.extend(chunk)
    end = [a for a in collected if a.name == "end_turn"]
    assert len(end) == 1
    assert end[0].kind == "click"


def test_planner_recruit_uses_memory_counts(tmp_path: Path) -> None:
    planner = Planner(_config(tmp_path, play_hand_minions=True,
                              buy_to_hand=False), clock=FakeClock())
    snap = _snap(PHASE_RECRUIT, turn=1, notes={"shop": [1, 2], "hand": [1]})
    actions: list[PlannedAction] = []
    for _ in range(20):
        chunk = planner.plan(snap)
        if not chunk:
            break
        actions.extend(chunk)
    buy_drags = [a for a in actions if a.kind == "drag" and a.name.startswith("buy_shop_")]
    play_drags = [a for a in actions if a.kind == "drag" and a.name.startswith("play_hand_")]
    assert len(buy_drags) == 2
    assert len(play_drags) == 1


def test_planner_shop_layout_centered(tmp_path: Path) -> None:
    """内存里 4 个 offer → 商店首格 x 应为 0.5-(1.5)*spacing（实测 image x≈765）。"""
    planner = Planner(_config(tmp_path, buy_to_hand=False), clock=FakeClock())
    snap = _snap(PHASE_RECRUIT, turn=1, notes={"shop": [0, 1, 2, 3]})
    actions: list[PlannedAction] = []
    for _ in range(20):
        chunk = planner.plan(snap)
        if not chunk:
            break
        actions.extend(chunk)
    buy = [a for a in actions if a.kind == "drag" and a.name == "buy_shop_0"][0]
    spacing = planner.config.coords.layout["shop_spacing"]
    assert abs(buy.x - (0.5 - 1.5 * spacing)) < 1e-4
    assert abs(buy.y - planner.config.coords.layout["shop_y"]) < 1e-4
    # 落点：buy_to_hand=False → 棋盘 y（实测 0.715 可出牌）
    assert abs(buy.y2 - planner.config.coords.layout["board_y"]) < 1e-4


def test_planner_hand_play_uses_hand_layout(tmp_path: Path) -> None:
    """买 N 张到手后应继续把 N 张手牌打到棋盘（源点用手牌布局，落点用棋盘 y）。"""
    planner = Planner(_config(tmp_path), clock=FakeClock())
    snap = _snap(PHASE_RECRUIT, turn=1, notes={"shop": [0, 1], "hand": []})
    actions: list[PlannedAction] = []
    for _ in range(20):
        chunk = planner.plan(snap)
        if not chunk:
            break
        actions.extend(chunk)
    layout = planner.config.coords.layout
    plays = [a for a in actions if a.kind == "drag"
             and a.name.startswith("play_hand_")]
    assert len(plays) == 2
    for act in plays:
        assert abs(act.y - layout["hand_y"]) < 1e-4
        assert abs(act.y2 - layout["board_y"]) < 1e-4


def test_planner_choice_once(tmp_path: Path) -> None:
    planner = Planner(_config(tmp_path), clock=FakeClock())
    snap = _snap(PHASE_CHOICE, turn=3, notes={"choice_serial": 7})
    actions = planner.plan(snap)
    assert [a.kind for a in actions] == ["click", "wait", "click", "wait"]
    assert actions[0].name == "choice_option_0"
    assert actions[2].name == "choice_confirm"
    assert planner.plan(snap) == []  # 同一选择事件只点一次
    # 新的选择事件（serial 变化）→ 再处理
    assert planner.plan(_snap(PHASE_CHOICE, turn=3,
                              notes={"choice_serial": 8}))


def test_planner_game_over_once(tmp_path: Path) -> None:
    planner = Planner(_config(tmp_path), clock=FakeClock())
    snap = _snap(PHASE_GAME_OVER, turn=6, in_game=False, placement=4)
    actions = planner.plan(snap)
    assert [a.kind for a in actions] == ["screenshot", "click", "wait"]
    # 结算页先点「继续/返回」回大厅，而不是盲点大厅坐标（避免误触退出）
    assert actions[1].name == "result_continue"
    assert planner.plan(snap) == []
    # 下一局可以再处理
    assert planner.plan(_snap(PHASE_GAME_OVER, turn=8, game=2, in_game=False))


def test_planner_blind_mode(tmp_path: Path) -> None:
    clock = FakeClock()
    cfg = _config(tmp_path, blind_turn_s=1.0, blind_game_duration_s=5.0)
    planner = Planner(cfg, clock=clock)
    kinds: list[str] = []
    for _ in range(200):
        actions = planner.plan(None, now=clock.now)
        actions and kinds.extend(a.kind for a in actions)
        if actions and any(a.kind == "screenshot" for a in actions):
            break
        clock.advance(1.0)
    assert "click" in kinds and "drag" in kinds
    assert planner.blind_games_completed >= 1


# ══════════════════════════════════════════════════════════════════════
# Runner（dry-run 主循环）
# ══════════════════════════════════════════════════════════════════════


def _collect_logs() -> tuple[list[str], callable]:
    lines: list[str] = []
    return lines, (lambda msg: lines.append(msg))


def test_livebot_dry_run_simulated(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    logs, logger = _collect_logs()
    watcher = SimulatedWatcher(cfg, games=2)
    bot = LiveBot(cfg, live=False, watcher=watcher,
                  out_dir=tmp_path / "sess", sleep_fn=lambda _s: None,
                  logger=logger, auto_memory=False)
    summary = bot.run(max_games=2)
    assert summary.games_played == 2
    assert summary.errors == 0
    assert summary.dry_run is True
    assert summary.simulated is True
    assert (tmp_path / "sess" / "records.jsonl").exists()
    records = _read_jsonl(tmp_path / "sess" / "records.jsonl")
    assert len(records) == 2
    for record in records:
        for key in ("game_no", "game_id", "started_at", "ended_at",
                    "duration_s", "turns", "placement", "reason",
                    "power_log", "hdt_log", "actions"):
            assert key in record
        assert record["dry_run"] is True
    assert (tmp_path / "sess" / "events.jsonl").exists()
    summary_json = json.loads(
        (tmp_path / "sess" / "summary.json").read_text(encoding="utf-8"))
    assert summary_json["games_played"] == 2
    text = "\n".join(logs)
    assert "[PLAN]" in text
    assert "click menu_battlegrounds" in text
    assert "game 1 end" in text
    # dry-run 绝不真实点击：底层 DryRunBackend 没有收到 click/drag/key 调用
    backend = bot.controller.backend
    assert not any(name in ("click", "drag", "key") for name, _ in backend.calls)


def test_livebot_phase_transitions_logged(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    logs, logger = _collect_logs()
    watcher = SimulatedWatcher(cfg, games=1)
    bot = LiveBot(cfg, live=False, watcher=watcher,
                  out_dir=tmp_path / "sess2", sleep_fn=lambda _s: None,
                  logger=logger, auto_memory=False)
    bot.run(max_games=1)
    events = _read_jsonl(tmp_path / "sess2" / "events.jsonl")
    kinds = {e["event"] for e in events}
    assert "start" in kinds and "stop" in kinds
    assert "game_start" in kinds and "game_end" in kinds


def test_livebot_handles_errors_and_stops(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.safety.max_consecutive_errors = 2

    class BadController:
        dry_run = True

        def __init__(self) -> None:
            self.pause = None
            self.calls = 0

        def click(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("boom")

        def drag(self, *args, **kwargs):
            raise RuntimeError("boom")

        def key(self, *args, **kwargs):
            raise RuntimeError("boom")

        def wait(self, *args, **kwargs):
            return None

        def screenshot(self, *args, **kwargs):
            return None

        def close(self):
            pass

    controller = BadController()
    watcher = SimulatedWatcher(cfg, games=1)
    logs, logger = _collect_logs()
    bot = LiveBot(cfg, live=False, controller=controller, watcher=watcher,
                  out_dir=tmp_path / "sess3", sleep_fn=lambda _s: None,
                  logger=logger, auto_memory=False)
    summary = bot.run(max_games=1)
    assert summary.errors >= 1
    assert summary.reason in ("too_many_errors", "max_games")
    events = _read_jsonl(tmp_path / "sess3" / "events.jsonl")
    assert any(e["event"] == "error" for e in events)


def test_client_alive_and_power_log_helpers(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    bot = LiveBot(cfg, live=False, watcher=SimulatedWatcher(cfg, games=1),
                  out_dir=tmp_path / "sess_helpers",
                  sleep_fn=lambda _s: None, auto_memory=False)
    # dry-run 下始终视为存活（不会误触发重启）
    assert bot._client_alive() is True
    # 新鲜 Power.log 优先使用快照路径
    power = tmp_path / "Power.log"
    power.write_text("x", encoding="utf-8")
    snap = LiveSnapshot(power_log_path=str(power))
    assert bot._power_log_path_now(snap) == str(power)
    # 快照为空时也不崩溃，返回字符串
    assert isinstance(bot._power_log_path_now(None), str)
    # 每局结束把 Power.log 归档到会话目录（防下一秒截断复用）
    src = tmp_path / "Power.log"
    src.write_text("a\n" * 50, encoding="utf-8")
    archived = bot._archive_power_log(str(src), 3)
    assert archived is not None and archived.exists()
    assert archived.name == "game_03_Power.log"
    assert archived.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_game_over_stuck_retry_cap(tmp_path: Path) -> None:
    """结算页重试有上限，超限后停止并记 game_over_stuck（不盲点）。"""
    cfg = _config(tmp_path)
    cfg.flow.max_game_over_retries = 2
    clock = FakeClock()

    class FakeController:
        dry_run = True
        pause = None

        def __init__(self) -> None:
            self.clicks = []
            self.keys = []

        def click(self, *args, **kwargs):
            self.clicks.append((args, kwargs))

        def key(self, *args, **kwargs):
            self.keys.append((args, kwargs))

        def drag(self, *args, **kwargs):
            pass

        def wait(self, *args, **kwargs):
            pass

        def screenshot(self, *args, **kwargs):
            return None

        def close(self):
            pass

    controller = FakeController()
    bot = LiveBot(cfg, live=False, controller=controller,
                  watcher=SimulatedWatcher(cfg, games=1),
                  out_dir=tmp_path / "sess_stuck", clock=clock,
                  sleep_fn=lambda s: clock.advance(max(0.01, s)),
                  auto_memory=False)
    for _ in range(6):
        bot._handle_game_over_stuck(clock.now)
        clock.advance(3.0)
    assert bot._stop_requested is True
    assert bot.summary.reason == "game_over_stuck"
    assert controller.clicks, "应至少尝试点击结算页"
    events = _read_jsonl(tmp_path / "sess_stuck" / "events.jsonl")
    assert any(e["event"] == "game_over_nudge" for e in events)
    assert any(e["event"] == "game_over_stuck" for e in events)


def test_livebot_respects_max_games(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _, logger = _collect_logs()
    watcher = SimulatedWatcher(cfg, games=3)
    bot = LiveBot(cfg, live=False, watcher=watcher,
                  out_dir=tmp_path / "sess4", sleep_fn=lambda _s: None,
                  logger=logger, auto_memory=False)
    summary = bot.run(max_games=1)
    assert summary.games_played == 1
    assert summary.reason == "max_games"


def test_livebot_pause_blocks_actions(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.flow.max_runtime_s = 3.0
    clock = FakeClock()

    class AlwaysPaused:
        paused = True

        def poll_once(self) -> bool:
            return True

    logs, logger = _collect_logs()
    watcher = SimulatedWatcher(cfg, games=1)
    bot = LiveBot(cfg, live=False, watcher=watcher,
                  out_dir=tmp_path / "sess5",
                  clock=clock,
                  sleep_fn=lambda s: clock.advance(max(0.1, s * 20)),
                  logger=logger, auto_memory=False,
                  pause_controller=AlwaysPaused())
    summary = bot.run(max_games=1)
    assert summary.games_played == 0
    assert summary.reason == "max_runtime"
    assert not any("[PLAN]" in line for line in logs)


def test_livebot_game_timeout(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.flow.game_timeout_s = 0.0
    cfg.flow.max_runtime_s = 2.0
    clock = FakeClock()
    logs, logger = _collect_logs()
    watcher = SimulatedWatcher(cfg, games=5)
    bot = LiveBot(cfg, live=False, watcher=watcher,
                  out_dir=tmp_path / "sess6", clock=clock,
                  sleep_fn=lambda s: clock.advance(0.2),
                  logger=logger, auto_memory=False)
    summary = bot.run(max_games=2)
    records = _read_jsonl(tmp_path / "sess6" / "records.jsonl")
    assert records
    assert any(r["reason"] == "game_timeout" for r in records)


# ══════════════════════════════════════════════════════════════════════
# CLI / 校准工具
# ══════════════════════════════════════════════════════════════════════


def test_livebot_cli_dry_run(tmp_path: Path, capsys) -> None:
    script = _load_script("scripts/livebot.py", "hsbg_livebot_cli")
    out = tmp_path / "cli_session"
    code = script.main([
        "--games", "2", "--dry-run", "--simulate",
        "--out-dir", str(out), "--quiet",
    ])
    assert code == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured.strip().splitlines()[-1])
    assert payload["games_played"] == 2
    assert payload["dry_run"] is True
    assert payload["simulated"] is True
    assert (out / "records.jsonl").exists()


def test_livebot_cli_conflicting_flags(tmp_path: Path, capsys) -> None:
    script = _load_script("scripts/livebot.py", "hsbg_livebot_cli2")
    assert script.main(["--live", "--dry-run"]) == 2
    assert "不能同时" in capsys.readouterr().err
    assert script.main(["--live", "--simulate"]) == 2


def test_livebot_cli_live_missing_window(tmp_path: Path, capsys,
                                         monkeypatch) -> None:
    """--live 找不到窗口必须安全退出（不发送任何输入）。

    测试通过 monkeypatch 强制"找不到窗口"，确保绝不会真的进入 live 分支
    操作正在运行的游戏（测试环境禁止真实点击）。
    """
    script = _load_script("scripts/livebot.py", "hsbg_livebot_cli_nw")
    monkeypatch.setattr(script, "find_hearthstone_window", lambda cfg: None)
    code = script.main([
        "--live", "--games", "1",
        "--window-title", "Hsbg-No-Such-Window-Title-12345",
        "--out-dir", str(tmp_path / "live"),
    ])
    assert code == 2
    assert "找不到 Hearthstone 窗口" in capsys.readouterr().err
    assert not (tmp_path / "live").exists()


def test_livebot_cli_list_coords_and_config(tmp_path: Path, capsys) -> None:
    script = _load_script("scripts/livebot.py", "hsbg_livebot_cli3")
    assert script.main(["--list-coords"]) == 0
    out = capsys.readouterr().out
    assert "menu_battlegrounds" in out and "group shop" in out
    assert script.main(["--show-config"]) == 0
    payload = json.loads(capsys.readouterr().out)
    expected = load_config(DEFAULT_CONFIG_PATH)
    assert payload["coords"]["points"]["menu_battlegrounds"] == [
        expected.coords.point("menu_battlegrounds")[0],
        expected.coords.point("menu_battlegrounds")[1],
    ]
    assert payload["coords"]["points"]["lobby_play"] == list(
        expected.coords.point("lobby_play"))


def test_livebot_cli_set_override(tmp_path: Path, capsys) -> None:
    script = _load_script("scripts/livebot.py", "hsbg_livebot_cli4")
    out = tmp_path / "cli_override"
    code = script.main([
        "--games", "1", "--dry-run", "--simulate", "--quiet",
        "--out-dir", str(out),
        "--set", "coords.points.menu_battlegrounds=0.48,0.38",
    ])
    assert code == 0
    config = json.loads(
        (out / "config_snapshot.json").read_text(encoding="utf-8"))
    assert config["coords"]["points"]["menu_battlegrounds"] == [0.48, 0.38]


def test_calibrate_tool(tmp_path: Path, capsys) -> None:
    image = ROOT / "runs" / "live" / "game_screen.png"
    if not image.exists():
        pytest.skip("缺少校准参考截图 runs/live/game_screen.png")
    tool = _load_script("tools/livebot_calibrate.py", "hsbg_livebot_calibrate")
    out = tmp_path / "calibrated.png"
    code = tool.main(["--image", str(image), "--out", str(out), "--json"])
    assert code == 0
    assert out.exists() and out.stat().st_size > 1000
    captured = capsys.readouterr().out
    assert "menu_battlegrounds" in captured
    assert "标注图已保存" in captured
