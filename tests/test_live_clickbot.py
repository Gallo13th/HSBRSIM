"""hsbg/live/click_bot 的校准/动作/启动链测试（不接触真实游戏）。

覆盖：
- 1600x900（37.0 new UI）坐标表与行布局；
- FREEZE / HERO_POWER（含目标）/ ACTIVATE / USE_DARK_GIFT / END_TURN
  的状态验证、失败截图/黑名单、每动作日志 note；
- 英雄选择（点解锁英雄卡 → 点确认）与“确认灰显不推进”；
- 启动链 _enter_game（只在明确状态点击，登录页只等待）；
- note 词表与 hsbg.env.spec.ActionKind 语义对齐。

平台守卫：``hsbg.live.click_bot → hsbg.live.launcher`` 在模块级执行
``ctypes.windll.user32``，非 Windows 上 import 即 AttributeError（收集错误）。
因此非 Windows 平台在 import 前整模块 skip；Windows 上行为不变（全部用例照跑）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

if sys.platform != "win32":
    pytest.skip(
        "hsbg.live.click_bot 依赖 Windows API（ctypes.windll / Win32 SendInput），"
        "非 Windows 平台按设计跳过；Windows 上照常执行",
        allow_module_level=True,
    )

from hsbg.env.spec import ActionKind
from hsbg.live import click_bot as cb
from hsbg.live.click_bot import ClickBot


# ---------------------------------------------------------------- fakes


class FakeWindow:
    hwnd = 1234
    client_rect = (0, 0, 1600, 900)
    process = "Hearthstone.exe"


class FakeBackend:
    def __init__(self) -> None:
        self.clicks: List[tuple] = []
        self.right_clicks: List[tuple] = []
        self.drags: List[tuple] = []
        self.keys: List[int] = []

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        if button == "right":
            self.right_clicks.append((x, y))
        else:
            self.clicks.append((x, y))

    def drag(self, points, duration: float = 0.35) -> None:  # noqa: ANN001
        self.drags.append((tuple(points[0]), tuple(points[-1])))

    def key(self, vk: int) -> None:
        self.keys.append(vk)

    def move(self, x: int, y: int) -> None:
        self.moves = getattr(self, "moves", [])
        self.moves.append((x, y))


class FakeStates:
    """按顺序返回状态；耗尽后固定返回最后一个。"""

    def __init__(self, states: List[Dict[str, Any]]) -> None:
        self.states = [dict(s) for s in states]
        self.calls = 0

    def next(self) -> Dict[str, Any]:
        self.calls += 1
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0] if self.states else {}


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """动作验证里的 sleep 不影响测试速度。"""
    monkeypatch.setattr(cb.time, "sleep", lambda *_a, **_k: None)


def make_bot(tmp_path: Path, monkeypatch, states, **kwargs: Any):
    monkeypatch.setattr(cb, "find_hearthstone_window", lambda: None)
    bot = ClickBot(tmp_path, auto_launch=False, safe_state=False,
                   action_shots=False, **kwargs)
    bot._window = FakeWindow()
    bot.backend = FakeBackend()
    bot.l, bot.t, bot.r, bot.b = 0, 0, 1600, 900
    bot._focus = lambda: True
    shots: List[str] = []
    bot.screenshot = lambda tag, subdir=None: (shots.append(tag) or None)
    fs = FakeStates(states)
    bot.state = fs.next
    return bot, fs, shots


def read_log(bot: ClickBot) -> List[Dict[str, Any]]:
    path = bot.out_dir / "actions.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def legal(**over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "end": False, "refresh": False, "freeze": False, "upgrade": False,
        "dark_gift": False, "powers": {}, "buy": [], "sell": [], "activate": {},
        "play": {}, "choose": [], "choice_spots": [], "choice_shown": 0,
        "choice_refs": [], "hero_free_rerolls": 0, "hero_reroll": [],
    }
    base.update(over)
    return base


def minion(card: str = "BG_TEST_1", atk: int = 2, hp: int = 2, cost: int = 3,
           eid: int = 101, kind: str = "minion", frozen: bool = False,
           **over: Any) -> Dict[str, Any]:
    item = {"kind": kind, "card": card, "eid": eid, "atk": atk, "hp": hp,
            "cost": cost, "frozen": frozen, "tier": 1, "keywords": [],
            "minion": {"card": card, "atk": atk, "hp": hp, "tier": 1}}
    item.update(over)
    return item


def make_state(*, phase: str = "recruit", turn: int = 3, gold: int = 5,
               tier: int = 2, shop=None, hand=None, board=None, choices=None,
               powers=None, legal_=None, pending=None) -> Dict[str, Any]:
    return {
        "schema": "hsbg.live_state.v1",
        "phase": phase, "turn": turn, "gold": gold, "tier": tier,
        "health": 30, "armor": 0, "alive": True, "alive_count": 8,
        "shop": shop or [], "hand": hand or [], "board": board or [],
        "choices": choices or [], "powers": powers or [],
        "legal": legal_ if legal_ is not None else legal(),
        "pending": pending, "waiting": "",
    }


def px(fx: float, fy: float) -> tuple:
    return (int(fx * 1600), int(fy * 900))


# ---------------------------------------------------------------- 布局常量


def test_layout_points_follow_calibration() -> None:
    """行布局使用 37.0 new UI 实测中心/间距（1600x900）。"""
    def close(point, want, tol=1):
        assert abs(point[0] - want[0]) <= tol and abs(point[1] - want[1]) <= tol

    close(px(*cb.MENU_BATTLEGROUNDS), (800, 340))
    close(px(*cb.HERO_CONFIRM), (800, 710))
    close(px(*cb.FREEZE_BTN), (1020, 119))
    close(px(*cb.HERO_POWER_BTN), (940, 690))
    close(px(*cb.DARK_GIFT_BTN), (1340, 237))


def test_row_points_centered(tmp_path, monkeypatch) -> None:
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [make_state()])
    shop = bot._shop_pts(4)
    assert [round(x, 3) for x, _y in shop] == [0.384, 0.461, 0.539, 0.616]
    assert all(y == cb.SHOP_Y for _x, y in shop)
    hand = bot._hand_pts(2)
    assert [round(x, 3) for x, _y in hand] == [0.434, 0.496]
    board = bot._board_pts(1)
    assert board == [(0.5, cb.BOARD_Y)]


# ---------------------------------------------------------------- FREEZE


def test_freeze_shop_success(tmp_path, monkeypatch) -> None:
    shop = [minion("A", 1, 1, eid=1), minion("B", 2, 2, eid=2)]
    st0 = make_state(shop=shop, legal_=legal(freeze=True))
    st1 = make_state(shop=[dict(shop[0], frozen=True), dict(shop[1], frozen=True)],
                     legal_=legal(freeze=True))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st1])
    assert bot.freeze_shop(st0) is True
    assert bot.backend.clicks == [px(*cb.FREEZE_BTN)]
    notes = [r.get("note") for r in read_log(bot) if r.get("kind") == "click"]
    assert notes == ["freeze"]


def test_freeze_shop_failure_blacklists_and_screenshots(tmp_path, monkeypatch) -> None:
    shop = [minion("A", 1, 1, eid=1)]
    st0 = make_state(shop=shop, legal_=legal(freeze=True))
    bot, _fs, shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.freeze_shop(st0) is False
    assert "freeze" in bot.failed
    logs = read_log(bot)
    assert any(r.get("kind") == "no_effect" and r.get("key") == "freeze" for r in logs)
    assert "fail_" in "?" or shots  # 失败截图被调用
    assert any(s.startswith("fail_") for s in shots)


def test_freeze_shop_requires_legal(tmp_path, monkeypatch) -> None:
    st0 = make_state(shop=[minion()], legal_=legal(freeze=False))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.freeze_shop(st0) is False
    assert bot.backend.clicks == []


# ---------------------------------------------------------------- HERO POWER


def test_use_hero_power_with_target(tmp_path, monkeypatch) -> None:
    shop = [minion("A", 1, 1, eid=11), minion("B", 2, 2, eid=12)]
    powers = [{"card": "BG20_HERO_100p", "usable": True, "price": 1}]
    legal0 = legal(powers={"0": {"targets": [{"zone": "shop", "index": 0}],
                                "modes": None, "valid": True}})
    legal1 = legal(powers={})
    st0 = make_state(shop=shop, legal_=legal0, powers=powers)
    st1 = make_state(shop=shop, legal_=legal0, powers=powers)      # 点技能后
    st2 = make_state(shop=shop, legal_=legal1, powers=powers, gold=4)  # 目标结算
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0, st1, st2])
    assert bot.use_hero_power(st0) is True
    assert bot.backend.clicks[0] == px(*cb.HERO_POWER_BTN)
    shop_pts = bot._shop_pts(len(shop))
    assert bot.backend.clicks[1] == px(*shop_pts[0])
    notes = [r.get("note", "") for r in read_log(bot) if r.get("kind") == "click"]
    assert any(n.startswith("hero_power:") for n in notes)
    assert any(n.startswith("hero_power_target:shop[0]") for n in notes)


def test_use_hero_power_no_targets_verifies_state_change(tmp_path, monkeypatch) -> None:
    powers = [{"card": "P1", "usable": True, "price": 0}]
    st0 = make_state(powers=powers,
                     legal_=legal(powers={"0": {"targets": [], "valid": True}}))
    st1 = make_state(powers=powers, legal_=legal(powers={}), gold=3)
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0, st1])
    assert bot.use_hero_power(st0) is True


def test_use_hero_power_requires_legal(tmp_path, monkeypatch) -> None:
    st0 = make_state(legal_=legal(powers={}))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.use_hero_power(st0) is False
    assert bot.backend.clicks == []


# ---------------------------------------------------------------- ACTIVATE


def test_activate_minion_with_target(tmp_path, monkeypatch) -> None:
    board = [minion("BG36_900", 3, 3, eid=77)]
    act = {"0": {"targets": [{"zone": "board", "index": 0}], "valid": True}}
    st0 = make_state(board=board, legal_=legal(activate=dict(act)))
    st1 = make_state(board=board, legal_=legal(activate=dict(act)))
    st2 = make_state(board=[minion("BG36_900", 5, 5, eid=77)],
                     legal_=legal(activate={}))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0, st1, st2])
    assert bot.activate_minion(st0) is True
    assert bot.backend.clicks[0] == px(*bot._board_pts(1)[0])
    notes = [r.get("note", "") for r in read_log(bot) if r.get("kind") == "click"]
    assert notes[0] == "activate:BG36_900"
    assert any(n.startswith("activate_target:board[0]") for n in notes)


def test_activate_minion_requires_legal(tmp_path, monkeypatch) -> None:
    st0 = make_state(board=[minion()], legal_=legal(activate={}))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.activate_minion(st0) is False
    assert bot.backend.clicks == []


# ---------------------------------------------------------------- DARK GIFT


def test_use_dark_gift_then_choose(tmp_path, monkeypatch) -> None:
    shop = [minion("A", 1, 1, eid=1)]
    choices3 = [
        {"kind": "minion", "card": f"DG_{i}", "eid": 900 + i,
         "minion": {"card": f"DG_{i}", "attached": ["GIFT"]}}
        for i in range(3)
    ]
    st0 = make_state(gold=6, shop=shop, legal_=legal(dark_gift=True))
    st1 = make_state(gold=3, shop=shop, choices=choices3, pending="discover",
                     legal_=legal(choose=[0, 1, 2], dark_gift=False))
    st2 = make_state(gold=3, shop=shop, choices=[], pending=None,
                     legal_=legal(choose=[], dark_gift=False))
    bot, _fs, shots = make_bot(tmp_path, monkeypatch, [st1, st2])
    assert bot.use_dark_gift(st0) is True
    assert bot.backend.clicks == [px(*cb.DARK_GIFT_BTN)]
    # 三选一：应点中间卡（布局点）后 choices 清空
    assert bot.do_choice(st1) is True
    assert len(bot.backend.clicks) == 2
    notes = [r.get("note", "") for r in read_log(bot) if r.get("kind") == "click"]
    assert notes[0] == "use_dark_gift"
    assert notes[1].startswith("choose[0]:DG_0")
    assert not any(s.startswith("fail_") for s in shots)


def test_use_dark_gift_requires_legal(tmp_path, monkeypatch) -> None:
    st0 = make_state(legal_=legal(dark_gift=False))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.use_dark_gift(st0) is False
    assert bot.backend.clicks == []


def test_choice_layout_trinket_uses_confirm(tmp_path, monkeypatch) -> None:
    """饰品商店四选一：点卡后还需点「确认」(0.5,0.713)。"""
    choices4 = [{"kind": "spell", "card": f"TR_{i}"} for i in range(4)]
    st0 = make_state(gold=8, pending="trinket",
                     choices=choices4, legal_=legal(choose=[0, 1, 2, 3]))
    st1 = make_state(gold=8, pending="trinket",
                     choices=choices4, legal_=legal(choose=[0, 1, 2, 3]))
    st2 = make_state(gold=7, pending=None, choices=[], legal_=legal(choose=[]))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0, st1, st2])
    assert bot.do_choice(st0) is True
    # 第一次点选项，第二次点确认
    assert bot.backend.clicks[1] == px(*cb.CHOICE_CONFIRM)
    notes = [r.get("note", "") for r in read_log(bot) if r.get("kind") == "click"]
    assert notes[1] == "choice_confirm"


# ---------------------------------------------------------------- END TURN


def test_end_turn_no_manual_button_logs_auto_timer(tmp_path, monkeypatch) -> None:
    st0 = make_state(legal_=legal(end=True))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.end_turn(st0) is False           # 不谎报成功
    assert 0x45 in bot.backend.keys             # 试过 E 键
    logs = read_log(bot)
    unavail = [r for r in logs if r.get("kind") == "end_turn_unavailable"]
    assert len(unavail) == 1
    assert unavail[0]["note"] == "end_turn:auto_timer"
    # 同一回合只尝试一次
    clicks_before = len(bot.backend.clicks)
    assert bot.end_turn(st0) is False
    assert len(bot.backend.clicks) == clicks_before


def test_end_turn_success_on_phase_change(tmp_path, monkeypatch) -> None:
    st0 = make_state(turn=3, legal_=legal(end=True))
    st1 = make_state(turn=4, legal_=legal(end=True))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0, st1])
    assert bot.end_turn(st0) is True


def test_end_turn_requires_legal_end(tmp_path, monkeypatch) -> None:
    st0 = make_state(legal_=legal(end=False))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.end_turn(st0) is False
    assert bot.backend.clicks == []


# ---------------------------------------------------------------- HERO SELECT


def test_hero_select_clicks_card_then_confirm(tmp_path, monkeypatch) -> None:
    hs0 = make_state(phase="hero_select", turn=0,
                     choices=[{"kind": "hero", "card": "H1"},
                              {"kind": "hero", "card": "H2"}],
                     pending="hero")
    hs1 = make_state(phase="hero_select", turn=0, choices=[], pending="hero")
    rec = make_state(phase="recruit", turn=1)
    bot, _fs, shots = make_bot(tmp_path, monkeypatch, [hs0, hs1, rec])
    assert bot.do_hero(hs0) is True
    # 第一张解锁英雄卡是中间位（index 1），随后点确认
    assert bot.backend.clicks[0] == px(*cb.HERO_OPTIONS[1])
    assert bot.backend.clicks[1] == px(*cb.HERO_CONFIRM)
    logs = read_log(bot)
    assert any(r.get("kind") == "hero_selected" for r in logs)
    assert any(s.startswith("hero_selected") for s in shots)


def test_hero_select_retries_until_phase_change(tmp_path, monkeypatch) -> None:
    hsame = make_state(phase="hero_select", turn=0, pending="hero")
    rec = make_state(phase="recruit", turn=1)
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [hsame, hsame, hsame, rec])
    assert bot.do_hero(hsame) is True
    # 前两张卡(含一次确认)未推进 → 第三张卡 + 确认推进
    assert len(bot.backend.clicks) >= 4
    assert px(*cb.HERO_CONFIRM) in bot.backend.clicks


def test_hero_select_failure_blacklists(tmp_path, monkeypatch) -> None:
    hsame = make_state(phase="hero_select", turn=0, pending="hero")
    bot, _fs, shots = make_bot(tmp_path, monkeypatch, [hsame])
    assert bot.do_hero(hsame) is False
    assert "hero_select" in bot.failed
    assert any(s.startswith("fail_") or s == "hero_select_failed" for s in shots)


# ---------------------------------------------------------------- 启动链


def test_enter_game_from_menu(tmp_path, monkeypatch) -> None:
    menu = make_state(phase="no_active_game", turn=0)
    hero = make_state(phase="hero_select", turn=0, pending="hero")
    bot, _fs, shots = make_bot(tmp_path, monkeypatch, [menu, menu, hero])
    assert bot._enter_game(timeout_s=5.0) is True
    assert px(*cb.MENU_BATTLEGROUNDS) in bot.backend.clicks
    logs = read_log(bot)
    assert any(r.get("kind") == "start_game_ok" for r in logs)
    assert any(s == "start_game_ok" for s in shots)


def test_enter_game_waits_on_login_screen_without_clicking(tmp_path, monkeypatch) -> None:
    """phase 为空 = 登录页/启动页：只等待、只截图，绝不点击。"""
    login = make_state(phase="", turn=0)
    bot, _fs, shots = make_bot(tmp_path, monkeypatch, [login])
    assert bot._enter_game(timeout_s=0.02) is False
    assert bot.backend.clicks == []
    logs = read_log(bot)
    assert any(r.get("kind") == "start_wait" for r in logs)
    assert any(r.get("kind") == "start_failed" for r in logs)


def test_enter_game_from_game_over(tmp_path, monkeypatch) -> None:
    over = make_state(phase="game_over", turn=9)
    menu = make_state(phase="no_active_game", turn=0)
    hero = make_state(phase="hero_select", turn=0)
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [over, over, menu, hero])
    assert bot._enter_game(timeout_s=5.0) is True
    notes = [r.get("note") for r in read_log(bot) if r.get("kind") == "click"]
    assert "result_continue" in notes


# ---------------------------------------------------------------- note 对齐


def test_note_vocabulary_aligns_with_actionkind(tmp_path, monkeypatch) -> None:
    """新动作日志 note 前缀必须落在 env ActionKind 词表内。"""
    shop = [minion("A", 1, 1, eid=1)]
    powers = [{"card": "P1", "usable": True, "price": 1}]
    hs0 = make_state(phase="hero_select", turn=0, pending="hero")
    rec = make_state(phase="recruit", turn=1)
    st_freeze = make_state(shop=shop, legal_=legal(freeze=True))
    st_frozen = make_state(shop=[dict(shop[0], frozen=True)],
                           legal_=legal(freeze=True))
    st_hp0 = make_state(shop=shop, powers=powers,
                        legal_=legal(powers={"0": {"targets": [
                            {"zone": "shop", "index": 0}], "valid": True}}))
    st_hp1 = make_state(shop=shop, powers=powers,
                        legal_=legal(powers={"0": {"targets": [
                            {"zone": "shop", "index": 0}], "valid": True}}))
    st_hp2 = make_state(shop=shop, powers=powers, gold=4, legal_=legal(powers={}))
    st_end = make_state(legal_=legal(end=True))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch,
                                [rec,            # do_hero 卡片点击后
                                 rec,            # do_hero 确认后
                                 st_frozen,      # freeze 点击后
                                 st_hp1,         # hero power 点击后
                                 st_hp2,         # hero power 目标点击后
                                 st_end])        # end_turn 点击后
    bot.do_hero(hs0)
    bot.freeze_shop(st_freeze)
    bot.use_hero_power(st_hp0)
    bot.end_turn(st_end)

    kinds = {k.value for k in ActionKind}
    helper_prefixes = {"start", "menu_battlegrounds", "result_continue",
                       "hero_option", "hero_confirm", "choice_confirm",
                       "hero_power_target", "activate_target", "select",
                       "target"}
    seen = set()
    for rec_row in read_log(bot):
        note = str(rec_row.get("note") or "")
        if not note:
            continue
        prefix = note.split(":", 1)[0].split("[", 1)[0]
        seen.add(prefix)
        if prefix in helper_prefixes:
            continue
        assert prefix in kinds, f"note 前缀 {prefix!r} 不在 ActionKind 词表（note={note}）"
    assert {"freeze", "hero_power", "end_turn"} <= seen


# ---------------------------------------------------------------- 整局循环冒烟


def test_run_full_loop_with_fake_states(tmp_path, monkeypatch) -> None:
    """run() 冒烟：进入对局 → 动作 → 结算 → games 上限退出（全部 fake）。"""
    monkeypatch.setattr(cb, "find_hearthstone_window", lambda: FakeWindow())
    rec0 = make_state(phase="recruit", turn=1, gold=3,
                      shop=[minion("A", 2, 3, cost=3, eid=1)],
                      legal_=legal(buy=[0], refresh=True, end=True))
    rec1 = make_state(phase="recruit", turn=1, gold=0,
                      shop=[minion("B", 2, 2, cost=3, eid=2)],
                      legal_=legal(end=True))
    over = make_state(phase="game_over", turn=9)
    bot = ClickBot(tmp_path, auto_launch=False, safe_state=False,
                   action_shots=False, games=1, recruit_settle_s=0.0)
    bot.backend = FakeBackend()
    bot._focus = lambda: True
    bot.screenshot = lambda tag, subdir=None: None
    fs = FakeStates([rec0, rec1, over, over])
    bot.state = fs.next
    result = bot.run()
    assert result.get("games_done") == 1
    assert not result.get("error"), result
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["games_done"] == 1
    # 进入对局 + 买/等待都被记录
    logs = read_log(bot)
    assert any(r.get("kind") == "start_game_ok" for r in logs)
    assert any(r.get("kind") == "game_over" for r in logs)


def test_failed_spell_cancels_targeting(tmp_path, monkeypatch) -> None:
    """目标法术拖拽失败后会停在 targeting 模式：必须右键取消，否则后续动作全废。"""
    spell = minion("BG_TEST_SPELL", 0, 0, cost=1, eid=55, kind="spell")
    st0 = make_state(hand=[spell], legal_=legal(play={"0": {
        "positions": [0], "use": {"targets": [], "modes": None, "valid": True},
        "magnetize": []}}))
    bot, _fs, shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.play_hand(st0) is False
    assert bot.backend.right_clicks, "失败的目标法术必须触发右键取消 targeting"
    logs = read_log(bot)
    assert any(r.get("kind") == "cancel_targeting" for r in logs)
    assert any(r.get("kind") == "no_effect" for r in logs)


def test_recruit_settle_waits_for_intro(tmp_path, monkeypatch) -> None:
    """入局动画期间（turn<=1）不动作，只等待；settle 过后才决策。"""
    rec = make_state(phase="recruit", turn=1, gold=3,
                     shop=[minion("A", 2, 2, cost=3, eid=1)],
                     legal_=legal(buy=[0], end=True))
    over = make_state(phase="game_over", turn=9)
    bot = ClickBot(tmp_path, auto_launch=False, safe_state=False,
                   action_shots=False, games=1, recruit_settle_s=0.3)
    bot.backend = FakeBackend()
    bot._focus = lambda: True
    bot.screenshot = lambda tag, subdir=None: None
    fs = FakeStates([rec, rec, over, over])
    bot.state = fs.next
    result = bot.run()
    assert not result.get("error"), result
    logs = read_log(bot)
    assert any(r.get("kind") == "recruit_settle" for r in logs)


def test_choose_one_target_spell_uses_legal_modes(tmp_path, monkeypatch) -> None:
    """Choose One + 需要目标：用 legal.play[].use.modes 的目标列表两段式施放。"""
    board = [minion("BG_TEST_A", 2, 2, eid=1)]
    spell = minion("BG31_880", 0, 0, cost=1, eid=55, kind="spell")
    entry = {"positions": [0],
             "use": {"targets": [],
                     "modes": [[{"zone": "board", "index": 0}]],
                     "valid": True},
             "magnetize": []}
    st0 = make_state(hand=[spell], board=board, gold=5,
                     legal_=legal(play={"0": entry}))
    st_done = make_state(hand=[], board=board, gold=4,
                         legal_=legal(play={}))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0, st_done])
    assert bot.play_hand(st0) is True
    assert bot.backend.drags, "必须先拖到目标随从"
    dest = bot.backend.drags[0][1]
    assert dest == px(*bot._board_pts(1)[0])
    notes = [r.get("note", "") for r in read_log(bot) if r.get("kind") == "drag"]
    assert notes and notes[0].startswith("play_spell:BG31_880->board[0]")


class FlakyStates:
    """交替返回“正常状态/脏帧”，模拟战斗过渡时内存状态抖动。"""

    def __init__(self, normal, flicker):
        self.normal = normal
        self.flicker = flicker
        self.i = 0

    def next(self):
        self.i += 1
        return self.flicker if self.i % 2 == 0 else self.normal


def test_changed_filters_transient_flicker(tmp_path, monkeypatch) -> None:
    """单帧抖动不算“动作成功”：必须连续两帧一致（run 0034 卡死问题的回归）。"""
    normal = make_state(hand=[minion("A", 1, 1, eid=1)], gold=3)
    flicker = make_state(hand=[], gold=3)          # 脏帧：hand 数量抖动
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [normal])
    bot.state = FlakyStates(normal, flicker).next
    before = bot._sig(normal)
    assert bot._changed(before, timeout=0.35) is False


def test_changed_accepts_stable_change(tmp_path, monkeypatch) -> None:
    normal = make_state(hand=[minion("A", 1, 1, eid=1)], gold=3)
    changed = make_state(hand=[], gold=3)          # 稳定变化（连续两帧一致）
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [normal])
    bot.state = lambda: changed
    before = bot._sig(normal)
    assert bot._changed(before, timeout=0.35) is True


def test_play_hand_attempt_guard_limits_retries(tmp_path, monkeypatch) -> None:
    """同一张手牌每回合最多 2 次真实拖拽（主拖+1 次兜底），避免重复点击。"""
    mn = minion("BG_TEST_M", 1, 1, cost=3, eid=77, kind="minion")
    st0 = make_state(hand=[mn], board=[minion("A", 1, 1, eid=1)], gold=3,
                     legal_=legal(play={"0": {"positions": [0],
                                              "use": {"targets": [],
                                                      "modes": None,
                                                      "valid": True},
                                              "magnetize": []}}))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    calls = {"n": 0}

    def flaky(before, timeout=3.0):
        calls["n"] += 1
        return calls["n"] >= 2          # 第 1 次失败（触发兜底），第 2 次成功

    bot._changed = flaky
    for _ in range(4):
        bot.play_hand(st0)
    assert len(bot.backend.drags) == 2, bot.backend.drags


def test_play_hand_attempt_counter_resets_per_turn(tmp_path, monkeypatch) -> None:
    spell = minion("BG36_520t", 0, 0, cost=1, eid=77, kind="spell")
    st0 = make_state(hand=[spell], gold=3,
                     legal_=legal(play={"0": {"positions": [0],
                                              "use": {"targets": [],
                                                      "modes": None,
                                                      "valid": True},
                                              "magnetize": []}}))
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    bot._changed = lambda before, timeout=3.0: True
    bot._played_this_turn["play:77:BG36_520t"] = 2
    bot.play_hand(st0)
    assert bot.backend.drags == []
    bot._played_this_turn.clear()                          # 新回合
    bot.play_hand(st0)
    assert len(bot.backend.drags) == 1


def test_choice_stale_frame_not_clicked(tmp_path, monkeypatch) -> None:
    """choices 非空但 legal.choose 为空（战斗滞后帧）→ 禁止盲点。"""
    st0 = make_state(choices=[{"card": "X"}] * 5,
                     legal_=legal(choose=[]), pending="discover")
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.do_choice(st0) is False
    assert bot.backend.clicks == []
    logs = read_log(bot)
    assert any(r.get("kind") == "stale_choice_ignored" for r in logs)


def test_choice_five_option_layout_falls_back_to_hide(tmp_path, monkeypatch) -> None:
    """5 选 1 未知布局：点完候选布局后点「隐藏」，记录 choice_layout_unknown 且本回合不再重试。"""
    choices = [{"card": f"BG34_Giant_{i}"} for i in range(5)]
    st0 = make_state(choices=choices, legal_=legal(choose=[0, 1, 2, 3, 4]),
                     pending="discover", turn=8)
    bot, _fs, _shots = make_bot(tmp_path, monkeypatch, [st0])
    assert bot.do_choice(st0) is False
    notes = [r.get("note") for r in read_log(bot) if r.get("kind") == "click"]
    assert notes, "应该尝试点击候选布局"
    assert notes[-1] == "choice_hide"
    logs = read_log(bot)
    assert any(r.get("kind") == "choice_layout_unknown" for r in logs)
    assert bot._choice_fail_turn == 8
