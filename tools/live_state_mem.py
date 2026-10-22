"""实时状态读取（只读内存）——从 AgenticAssistant 的 Mono 读取器复用。

来源
----
本机 `AgenticAssistant.exe`（PyInstaller，Python 3.13）内含
`bgcontroller.client.mono` / `bgcontroller.client.memory`（只读 Mono 元数据读取，
仅 `PROCESS_QUERY_INFORMATION|PROCESS_VM_READ`，无注入、无写内存）与
`bgcontroller.client.mapping`（快照 → 模型 `GameState`/`Legal`）。
本脚本：
  1. 若未解包，用 `pyinstxtractor-ng` 把 EXE 的 PYZ 解到
     `reversed/rea/agentic_extract/`（已解包则直接复用；不修改 EXE）；
  2. `import bgcontroller.client.{memory,mapping}`（本地 Python 3.13 可原生加载其 .pyc）；
  3. 调 `capture_snapshot()` → `Mapper.frame()` → 压成稳定 JSON 字典；
  4. 提供 `read_live_state()` 库接口 + CLI 采样/持续观察（F9 暂停、F10 立即采样）。

输出 schema：`hsbg.live_state.v1`（见 `read_live_state.__doc__`）。

只读声明：本脚本不注入、不写游戏内存、不调用托管方法、不发送输入。

用法
----
  # 一次性读取（无对局时返回 no_active_game + attach 诊断）
  C:\\Python313\\python.exe tools\\live_state_mem.py
  # attach 诊断（进程/Mono 镜像/GameState 类）
  C:\\Python313\\python.exe tools\\live_state_mem.py --attach-test
  # 采样到文件
  C:\\Python313\\python.exe tools\\live_state_mem.py --sample runs\\live\\state_sample.json
  # 持续观察：F9 暂停/继续，F10 立即写一份；变化时写 latest + jsonl
  C:\\Python313\\python.exe tools\\live_state_mem.py --watch --interval 0.5 ^
      --out runs\\live\\state_latest.json --jsonl runs\\live\\state_stream.jsonl
  # fallback：从官方 Power.log 重建一帧（无活动对局/内存不可用时）
  C:\\Python313\\python.exe tools\\live_state_mem.py --from-powerlog ^
      --sample runs\\live\\state_from_powerlog_sample.json
  # 自测（不读游戏）
  C:\\Python313\\python.exe tools\\live_state_mem.py --self-test

注意：BG 对局中（含英雄选择）才有 GameState；主菜单/收藏返回 no_active_game。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import dataclasses
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
AGENTIC_DIR = ROOT / "AgenticAssistant"
AGENTIC_EXE = AGENTIC_DIR / "AgenticAssistant.exe"
AGENTIC_INTERNAL = AGENTIC_DIR / "_internal"
EXTRACT_ROOT = ROOT / "reversed" / "rea" / "agentic_extract"
EXTRACTED = EXTRACT_ROOT / "AgenticAssistant.exe_extracted"
PKG_DIR = EXTRACTED / "PYZ.pyz_extracted"
LOGS_ROOT = Path(r"C:\Program Files (x86)\Hearthstone\Logs")

SCHEMA = "hsbg.live_state.v1"
CATALOG_CANDIDATES = [
    AGENTIC_INTERNAL / "bgassistant" / "data" / "catalog.json",
    ROOT / "reversed" / "rizling_latest" / "bgassistant" / "data" / "catalog.json",
]

VK_F9 = 0x78
VK_F10 = 0x79
WM_HOTKEY = 0x0312

# ───────────────────────────── 解包 / 导入 ─────────────────────────────


def ensure_extracted(force: bool = False) -> Path:
    """确保 AgenticAssistant 的 PYZ 已解包（只读 EXE，不修改它）。返回 PYZ 目录。"""
    if force and EXTRACTED.exists():
        import shutil
        shutil.rmtree(EXTRACTED, ignore_errors=True)
    if (PKG_DIR / "bgcontroller" / "client" / "memory.pyc").exists():
        _ensure_data_dir()
        return PKG_DIR
    if not AGENTIC_EXE.exists():
        raise FileNotFoundError(f"未找到 {AGENTIC_EXE}")
    EXTRACT_ROOT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # pyinstxtractor-ng 输出到“当前工作目录/<exe 名>_extracted”
    cmd = [sys.executable, "-m", "pyinstxtractor_ng", str(AGENTIC_EXE)]
    proc = subprocess.run(cmd, cwd=str(EXTRACT_ROOT), capture_output=True,
                          text=True, timeout=600, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            "pyinstxtractor-ng 解包失败；先 `python -m pip install pyinstxtractor-ng`。\n"
            f"stdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}")
    if not EXTRACTED.exists():
        raise RuntimeError(f"解包产物不存在：{EXTRACTED}")
    _ensure_data_dir()
    if not (PKG_DIR / "bgcontroller" / "client" / "memory.pyc").exists():
        raise RuntimeError(f"解包后未找到 bgcontroller：{PKG_DIR}")
    return PKG_DIR


def _ensure_data_dir() -> None:
    """运行期需要两份数据：bgcontroller/data（tag 枚举）与 bgassistant/data（卡牌目录）。"""
    import shutil
    for rel in ("bgcontroller/data", "bgassistant/data"):
        dst = PKG_DIR / rel.replace("/", os.sep)
        src = AGENTIC_INTERNAL / rel.replace("/", os.sep)
        if dst.exists() or not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)


_SESSION: Dict[str, Any] = {}


def _load_modules():
    """把解包目录加入 sys.path 并导入 AgenticAssistant 的只读读取器。"""
    if "memory" in _SESSION:
        return _SESSION
    pkg = ensure_extracted()
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))
    from bgcontroller.client import memory as memory_mod  # type: ignore
    from bgcontroller.client import mapping as mapping_mod  # type: ignore
    from bgcontroller import state as state_mod  # type: ignore
    from bgcontroller import records as records_mod  # type: ignore
    from bgassistant import catalog as catalog_mod  # type: ignore
    from bgcontroller.client import powerlog as powerlog_mod  # type: ignore
    _SESSION.update(memory=memory_mod, mapping=mapping_mod,
                    state=state_mod, records=records_mod,
                    catalog=catalog_mod, powerlog=powerlog_mod, pkg=str(pkg))
    return _SESSION


def _mapper(mods: Optional[Dict[str, Any]] = None):
    """`Mapper` 需要卡牌目录表（Catalog），构造一次复用。"""
    mods = mods or _load_modules()
    if "mapper" not in _SESSION:
        table = mods["catalog"].Catalog()          # bgassistant/data/catalog.json
        _SESSION["mapper"] = mods["mapping"].Mapper(table)
    return _SESSION["mapper"]


# ───────────────────────────── attach / 诊断 ─────────────────────────────


def attach_info(pid: Optional[int] = None) -> Dict[str, Any]:
    """定位炉石进程与 Mono 模块（只读）。"""
    mods = _load_modules()
    info = mods["memory"].process_info(pid)
    out = {
        "pid": info.get("pid"),
        "mono_module": info.get("mono_module"),
        "mono_base": info.get("mono_base"),
        "mono_base_hex": hex(info["mono_base"]) if info.get("mono_base") else None,
    }
    return out


def attach_diagnostics(pid: Optional[int] = None) -> Dict[str, Any]:
    """更深的 attach 证据：Mono 镜像、GameState 类/静态实例是否可解析。

    主菜单（没有对局）时 GameState.s_instance 为 0、GameState 类可能尚未被 Mono 加载；
    这只说明“当前无对局”，不影响进程/Mono 模块 attach。
    """
    mods = _load_modules(); memory = mods["memory"]
    info = attach_info(pid)
    diag: Dict[str, Any] = {"process": info, "mono_image": None,
                            "game_state_class_found": None,
                            "game_state_instance": None,
                            "metadata_keys": None,
                            "note": ""}
    reader = None
    try:
        reader = memory.SnapshotReader(info["pid"])
        image = reader.attach_image(info["mono_base"])
        diag["mono_image"] = hex(image) if isinstance(image, int) else str(image)
        try:
            reader.bind_metadata(image)
            diag["metadata_keys"] = sorted(getattr(reader, "_metadata", {}) or {})
            diag["game_state_class_found"] = getattr(reader, "_game_state_class", None) is not None
            gs = reader.game_state(image)
            diag["game_state_instance"] = gs
            # 菜单下实例为 0，但 Mono 元数据/类布局仍可读：给出实体库指针链偏移
            cls_pair = getattr(reader, "_game_state_class", None)
            diag["game_state_class_found"] = cls_pair is not None
            if cls_pair:
                cls = (cls_pair[1] if isinstance(cls_pair, (tuple, list))
                       and len(cls_pair) > 1 else cls_pair)
                diag["game_state_class_ptr"] = (hex(cls) if isinstance(cls, int)
                                                else str(cls))
                try:
                    fields = reader.class_fields(cls)
                    fields = fields[0] if isinstance(fields, tuple) else fields
                    diag["game_state_fields"] = fields
                except Exception as exc2:  # noqa: BLE001
                    diag["fields_error"] = f"{type(exc2).__name__}: {exc2}"
                try:
                    offs = reader.field_offsets(cls, (
                        "m_entityMap", "m_playerMap", "m_choicesMap",
                        "m_gameEntity", "m_options", "m_queuedChoices",
                        "m_availableRacesInBattlegroundsExcludingAmalgam"))
                    diag["entity_db_offsets"] = (offs[1] if isinstance(offs, tuple)
                                                 else offs)
                except Exception as exc3:  # noqa: BLE001
                    diag["offsets_error"] = f"{type(exc3).__name__}: {exc3}"
        except Exception as exc:  # noqa: BLE001 - 诊断不抛出
            diag["metadata_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        diag["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:  # noqa: BLE001
                pass
    if diag.get("game_state_instance") in (None, 0):
        diag["note"] = ("当前无活动对局（GameState 静态实例为空）；"
                        "进入酒馆战棋对局（含英雄选择）后可读实体库。")
    return diag


# ───────────────────────────── 快照 → 字典 ─────────────────────────────


def _plain(value: Any) -> Any:
    """dataclass/frozenset/tuple/枚举 → JSON 友好结构。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name))
                for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


_CATALOG: Dict[str, Dict[str, Any]] = {}


def _catalog() -> Dict[str, Dict[str, Any]]:
    """card_id → {name, name_zh, kind, tier}（来自 AgenticAssistant 的公共目录）。"""
    if _CATALOG:
        return _CATALOG
    for path in CATALOG_CANDIDATES:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for card in data.get("cards") or []:
            cid = card.get("id")
            if cid:
                _CATALOG[cid] = {"name": card.get("name"),
                                 "name_zh": card.get("name_zh"),
                                 "kind": card.get("kind")}
        for skin, base in (data.get("skins") or {}).items():
            _CATALOG.setdefault(skin, _CATALOG.get(base, {}))
        break
    return _CATALOG


def _card_info(card_id: str) -> Dict[str, Any]:
    cat = _catalog().get(card_id or "", {})
    return {"card_id": card_id, "name": cat.get("name"),
            "name_zh": cat.get("name_zh")}


def _minion_dict(minion: Any, position: Optional[int] = None) -> Dict[str, Any]:
    d = _plain(minion)
    if position is not None:
        d["position"] = position
    info = _card_info(d.get("card") or "")
    d.update(info)
    d["golden"] = bool(d.get("golden"))
    d["keywords"] = list(d.get("keywords") or [])
    d["races"] = list(d.get("races") or [])
    d["attached"] = list(d.get("attached") or [])
    return d


def _item_dict(item: Any, position: Optional[int] = None,
               buyable: Optional[bool] = None,
               gold: int = 0) -> Dict[str, Any]:
    d = _plain(item)
    if position is not None:
        d["position"] = position
    d.update(_card_info(d.get("card") or ""))
    minion = d.get("minion")
    if minion is not None:
        # 兼容 asdict 后的 dict 或原对象
        m = _plain(minion) if not isinstance(minion, dict) else minion
        d["atk"] = m.get("atk")
        d["hp"] = m.get("hp")
        d["max_hp"] = m.get("max_hp")
        d["golden"] = bool(m.get("golden"))
        d["tier"] = m.get("tier")
        d["minion"] = m
    cost = d.get("cost")
    if buyable is not None:                    # 酒馆槽位：给“可否购买”语义
        d["affordable"] = (isinstance(cost, int) and cost <= gold)
        d["buyable"] = bool(buyable)           # 客户端 legal.buy 给出（服务器合法选项）
        d["can_buy"] = bool(d["buyable"] and d["affordable"])
    else:                                       # 手牌/其他区域
        d["affordable"] = None
        d["buyable"] = None
        d["can_buy"] = None
    return d


def _normalize_phase(state: Any, snap: Dict[str, Any],
                     legal: Dict[str, Any]) -> tuple[str, str]:
    raw = str(getattr(state, "phase", "") or "")
    if snap.get("game_over") or getattr(state, "alive", True) is False:
        return "game_over", raw
    # 注意：Legal.end = “可以结束回合”按钮，不是“对局结束”，不能用来判 game_over。
    if raw in ("recruit", "combat"):
        return raw, raw
    # 英雄选择：MULLIGAN 类型的选择在 show
    pending = str(getattr(state, "pending", "") or "").lower()
    choices = _plain(getattr(state, "choices", []) or [])
    for choice in choices if isinstance(choices, list) else []:
        if isinstance(choice, dict) and "MULLIGAN" in str(choice.get("type", "")).upper():
            return "hero_select", raw
    if "mulligan" in pending or "hero" in pending:
        return "hero_select", raw
    return (raw or "unknown"), raw


def frame_to_dict(frame: Any, snap: Optional[Dict[str, Any]] = None,
                  info: Optional[Dict[str, Any]] = None,
                  include_state: bool = False,
                  source: str = "agenticassistant.memory.capture_snapshot "
                                "+ mapping.Mapper.frame") -> Dict[str, Any]:
    """把 `bgcontroller.records.Frame` 压成稳定 JSON（见模块文档 schema）。"""
    state = getattr(frame, "state", None)
    legal = _plain(getattr(frame, "legal", None)) or {}
    buy = set(legal.get("buy") or [])
    gold = int(getattr(state, "gold", 0) or 0)
    phase, phase_raw = _normalize_phase(state, snap or {}, legal)

    def items(values: Iterable[Any], *, shop: bool = False) -> List[Dict[str, Any]]:
        out = []
        for idx, item in enumerate(values or []):
            out.append(_item_dict(item, idx, buyable=(idx in buy) if shop else None,
                                  gold=gold))
        return out

    board = [_minion_dict(m, i) for i, m in enumerate(getattr(state, "board", []) or [])]
    hand = items(getattr(state, "hand", []) or [])
    shop = items(getattr(state, "shop", []) or [], shop=True)
    hero_id = getattr(state, "hero", "") or ""
    out = {
        "schema": SCHEMA,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "read_only": True,
        "attached": True,
        "process": info or {},
        "phase": phase,
        "phase_raw": phase_raw,
        "pending": getattr(state, "pending", None),
        "pending_source": getattr(state, "pending_source", ""),
        "turn": int(getattr(state, "turn", 0) or 0),
        "gold": gold,
        "tier": int(getattr(state, "tier", 0) or 0),
        "tier7": bool(getattr(state, "tier7", False)),
        "alive": bool(getattr(state, "alive", True)),
        "alive_count": int(getattr(state, "alive_count", 0) or 0),
        "health": int(getattr(state, "health", 0) or 0),
        "armor": int(getattr(state, "armor", 0) or 0),
        "hero": _card_info(hero_id),
        "lobby_races": list(_plain(getattr(state, "lobby_races", []) or [])),
        "hand": hand,
        "board": board,
        "shop": shop,
        "choices": _plain(getattr(state, "choices", []) or []),
        "powers": _plain(getattr(state, "powers", []) or []),
        "trinkets": _plain(getattr(state, "trinkets", []) or []),
        "quests": _plain(getattr(state, "quests", []) or []),
        "rewards": _plain(getattr(state, "rewards", []) or []),
        "secrets": _plain(getattr(state, "secrets", []) or []),
        "opponents": _plain(getattr(state, "opponents", []) or []),
        "stats": _plain(getattr(state, "stats", {}) or {}),
        "legal": legal,
        "waiting": getattr(frame, "waiting", ""),
        "token": list(_plain(getattr(frame, "token", ()) or ())),
        "hand_costs": getattr(frame, "hand_costs", ""),
        "unbound": list(_plain(getattr(frame, "unbound", ()) or ())),
    }
    if include_state:
        out["state"] = _plain(state)
        out["snapshot"] = snap
    return out


# ───────────────────────────── 主读取接口 ─────────────────────────────


def read_live_state(pid: Optional[int] = None, include_state: bool = False,
                    attempts: int = 2) -> Dict[str, Any]:
    """读取当前实时状态（只读）。

    返回 `hsbg.live_state.v1`：
      phase: recruit / combat / hero_select / game_over / no_active_game / unavailable
      turn, gold, tier, health, armor, hero{card_id,name}
      hand[]/board[]/shop[]：position、card_id/name、atk/hp/cost、buyable/affordable …
      choices[]：英雄/饰品/发现/三选一等选择项（来自客户端 choices）
      legal{}：客户端给出的合法操作（buy/sell/refresh/upgrade/play/choose…）
    在菜单/收藏等无对局界面：attached=True、phase=no_active_game，并附 attach 诊断。
    """
    mods = _load_modules()
    memory, mapping = mods["memory"], mods["mapping"]
    try:
        info = attach_info(pid)
        try:
            snap = memory.capture_snapshot(pid=info["pid"], attempts=attempts)
        except memory.NoActiveGameState:
            diag = attach_diagnostics(info["pid"])
            return {
                "schema": SCHEMA,
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "source": "agenticassistant.memory",
                "read_only": True,
                "attached": True,
                "process": info,
                "phase": "no_active_game",
                "phase_raw": "",
                "note": "当前无活动对局（GameState 为空）；进入酒馆战棋对局后再采样。",
                "attach": diag,
            }
        except memory.SnapshotUnavailable as exc:
            return {
                "schema": SCHEMA,
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "read_only": True,
                "attached": True,
                "process": info,
                "phase": "unavailable",
                "error": f"{type(exc).__name__}: {exc}",
            }
        frame = _mapper(mods).frame(snap)
        if frame is None:
            return {
                "schema": SCHEMA,
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "read_only": True,
                "attached": True,
                "process": info,
                "phase": "unknown",
                "note": "快照未包含我方对局（Mapper.frame 返回 None）",
                "snapshot_meta": {k: snap.get(k) for k in
                                  ("schema", "captured_utc", "game_over",
                                   "game_identity", "read_calls", "bytes_read")},
            }
        return frame_to_dict(frame, snap, info, include_state=include_state)
    except FileNotFoundError as exc:
        return {"schema": SCHEMA, "attached": False, "phase": "unavailable",
                "error": str(exc)}


def read_state_from_powerlog(path: Optional[Path] = None,
                             want_phase: str = "recruit",
                             stride: int = 2000,
                             include_state: bool = False,
                             max_files: int = 5) -> Dict[str, Any]:
    """fallback：从官方 Power.log 重建某一帧（`LogGame.snapshot` → `Mapper.frame`）。

    内存读取不可用/无活动对局时的等价通道；Power.log 是服务器下发的 PowerHistory，
    与内存快照走同一个 `Mapper`，因此字段 schema 完全一致（但**不是实时**）。
    """
    mods = _load_modules()
    powerlog, mapper = mods["powerlog"], _mapper(mods)
    if path is not None:
        files = [Path(path)]
    else:
        files = sorted(LOGS_ROOT.rglob("Power.log"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:max_files]
    if not files:
        return {"schema": SCHEMA, "phase": "unavailable", "attached": False,
                "source": "powerlog", "error": "未找到 Power.log（先启动游戏并开启日志）"}
    errors: List[str] = []
    for log_path in files:
        if not log_path.exists():
            continue
        game = powerlog.LogGame()
        best = None
        last_any = None
        line_no = 0
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                for line_no, line in enumerate(fh, 1):
                    game.feed(line)
                    if line_no % stride:
                        continue
                    snap = game.snapshot()
                    if snap.get("game_over"):
                        continue
                    try:
                        frame = mapper.frame(snap)
                    except Exception:  # noqa: BLE001 - 过渡态快照跳过
                        continue
                    if frame is None:
                        continue
                    st = frame.state
                    if want_phase not in ("any", str(getattr(st, "phase", ""))):
                        continue
                    if want_phase == "recruit" and not list(getattr(st, "shop", []) or []):
                        continue
                    last_any = (frame, snap, line_no)
                    if int(getattr(st, "gold", 0) or 0) > 0:
                        best = last_any
            if best is None:
                best = last_any
            if best is None:
                errors.append(f"{log_path}: 无匹配 {want_phase} 帧")
                continue
            frame, snap, line_no = best
            info = {"source": "powerlog", "log_file": str(log_path),
                    "log_line": line_no, "wanted_phase": want_phase}
            out = frame_to_dict(frame, snap, info, include_state=include_state,
                                source="powerlog.LogGame.snapshot + mapping.Mapper.frame")
            out["attached"] = False
            out["log_file"] = str(log_path)
            out["log_line"] = line_no
            return out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{log_path}: {type(exc).__name__}: {exc}")
    return {"schema": SCHEMA, "phase": "no_powerlog_frame", "attached": False,
            "source": "powerlog", "errors": errors}


# ───────────────────────────── 热键暂停 ─────────────────────────────


class Hotkeys:
    """F9 暂停/继续；F10 立即采样。RegisterHotKey 不采集输入内容。"""

    def __init__(self, enable: bool = True):
        self.enable = enable
        self.paused = threading.Event()
        self.force = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ids: List[int] = []
        self._user32 = ctypes.windll.user32

    def start(self) -> None:
        if not self.enable:
            return
        try:
            if not self._user32.RegisterHotKey(None, 1, 0, VK_F9):
                raise OSError("RegisterHotKey(F9) 失败（可能被占用）")
            if not self._user32.RegisterHotKey(None, 2, 0, VK_F10):
                raise OSError("RegisterHotKey(F10) 失败（可能被占用）")
            self._ids = [1, 2]
        except OSError as exc:
            print(f"[hotkey] 禁用：{exc}", file=sys.stderr)
            self.enable = False
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="live-state-hotkeys")
        self._thread.start()

    def _loop(self) -> None:
        msg = wt.MSG()
        while not self._stop.is_set():
            while self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY:
                    if int(msg.wParam) == 1:
                        if self.paused.is_set():
                            self.paused.clear()
                            print("[hotkey] 已继续", flush=True)
                        else:
                            self.paused.set()
                            print("[hotkey] 已暂停（F9 继续）", flush=True)
                    elif int(msg.wParam) == 2:
                        self.force.set()
                        print("[hotkey] 立即采样", flush=True)
            time.sleep(0.05)

    def stop(self) -> None:
        self._stop.set()
        for hid in self._ids:
            try:
                self._user32.UnregisterHotKey(None, hid)
            except Exception:  # noqa: BLE001
                pass
        self._ids = []


# ───────────────────────────── 写盘 / CLI ─────────────────────────────


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _fingerprint(state: Dict[str, Any]) -> tuple:
    """变化检测：避免每 0.5s 写重复样本。"""
    return (
        state.get("phase"), state.get("turn"), state.get("gold"),
        state.get("tier"), state.get("health"), state.get("armor"),
        json.dumps(state.get("board"), sort_keys=True, ensure_ascii=False),
        json.dumps(state.get("hand"), sort_keys=True, ensure_ascii=False),
        json.dumps(state.get("shop"), sort_keys=True, ensure_ascii=False),
        json.dumps(state.get("choices"), sort_keys=True, ensure_ascii=False),
        json.dumps(state.get("legal"), sort_keys=True, ensure_ascii=False),
    )


def watch(pid: Optional[int], interval: float, out: Optional[Path],
          jsonl: Optional[Path], max_seconds: Optional[float],
          hotkey: bool, include_state: bool) -> int:
    hk = Hotkeys(enable=hotkey)
    hk.start()
    started = time.monotonic()
    last_fp = None
    samples = 0
    print(f"[watch] interval={interval}s hotkey={'F9/F10' if hk.enable else 'off'}"
          f" out={out} jsonl={jsonl}", flush=True)
    try:
        while True:
            if max_seconds is not None and time.monotonic() - started > max_seconds:
                print("[watch] 达到 --max-seconds，退出", flush=True)
                return 0
            if hk.paused.is_set() and not hk.force.is_set():
                time.sleep(0.1)
                continue
            force = hk.force.is_set()
            hk.force.clear()
            try:
                state = read_live_state(pid, include_state=include_state)
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001 - 观察循环不退出
                print(f"[watch] 读取失败：{type(exc).__name__}: {exc}", flush=True)
                time.sleep(max(interval, 1.0))
                continue
            fp = _fingerprint(state)
            if force or fp != last_fp:
                samples += 1
                if out:
                    _write_json(out, state)
                if jsonl:
                    jsonl.parent.mkdir(parents=True, exist_ok=True)
                    with jsonl.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(state, ensure_ascii=False) + "\n")
                last_fp = fp
                phase = state.get("phase")
                print(f"[watch] #{samples} {datetime.now().strftime('%H:%M:%S')} "
                      f"phase={phase} turn={state.get('turn')} "
                      f"gold={state.get('gold')} shop={len(state.get('shop') or [])}", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[watch] 用户中断", flush=True)
        return 0
    finally:
        hk.stop()


def _self_test() -> int:
    """不读游戏，验证 dataclass/legal → JSON 转换。"""
    mods = _load_modules()
    state_mod, records = mods["state"], mods["records"]
    m = state_mod.Minion(card="BG25_001", atk=2, hp=1, max_hp=1, tier=1,
                         golden=False, keywords=frozenset({"TAUNT", "REBORN"}),
                         races=frozenset({"UNDEAD"}), eid=101)
    item = state_mod.Item(kind="minion", card="BG_GVG_085", cost=3, eid=102,
                          minion=state_mod.Minion(card="BG_GVG_085", atk=1, hp=2,
                                                  tier=1, eid=102))
    spell = state_mod.Item(kind="spell", card="BG27_004t", cost=2, eid=103)
    st = state_mod.GameState(turn=7, phase="recruit", gold=7, tier=3,
                             hero="BG20_HERO_100", health=25, armor=5,
                             alive=True, alive_count=6,
                             hand=[spell], board=[m], shop=[item, spell])
    legal = records.Legal(end=False, refresh=True, freeze=False, upgrade=True,
                          dark_gift=False, powers={"BG20_HERO_100p": True},
                          buy=(0,), sell=(), activate={}, play={}, choose=(),
                          choice_spots=(), choice_shown=0, choice_refs=(),
                          hero_free_rerolls=0, hero_reroll=())
    frame = records.Frame(state=st, legal=legal, token=("tok", 1))
    out = frame_to_dict(frame, snap={"game_over": False},
                        info={"pid": 0, "mono_module": "mock"})
    checks = [
        ("schema", out["schema"] == SCHEMA),
        ("phase", out["phase"] == "recruit"),
        ("turn/gold/tier", (out["turn"], out["gold"], out["tier"]) == (7, 7, 3)),
        ("board", len(out["board"]) == 1 and out["board"][0]["card"] == "BG25_001"),
        ("board keywords", "REBORN" in out["board"][0]["keywords"]),
        ("shop", len(out["shop"]) == 2),
        ("shop[0].buyable", out["shop"][0]["buyable"] is True),
        ("shop[1].buyable", out["shop"][1]["buyable"] is False),
        ("hero name resolved", out["hero"].get("name") == "Rokara"),
        ("legal", out["legal"].get("buy") == [0]),
    ]
    ok = True
    for name, passed in checks:
        print(("PASS" if passed else "FAIL"), name)
        ok = ok and passed
    print("\nsample:", json.dumps(out, ensure_ascii=False)[:400], "...")
    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="炉石酒馆战棋实时状态读取（只读内存）")
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--sample", type=Path, default=None, help="写一份 JSON 快照")
    ap.add_argument("--out", type=Path, default=None, help="watch 的最新快照路径")
    ap.add_argument("--jsonl", type=Path, default=None, help="watch 的变化流")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--hotkey", dest="hotkey", action="store_true", default=True,
                    help="F9 暂停/继续，F10 立即采样（默认开）")
    ap.add_argument("--no-hotkey", dest="hotkey", action="store_false")
    ap.add_argument("--include-raw", action="store_true",
                    help="附带完整 state/snapshot（大）")
    ap.add_argument("--attach-test", action="store_true")
    ap.add_argument("--from-powerlog", nargs="?", const="auto", default=None,
                    metavar="PATH", help="从 Power.log 重建一帧（fallback）")
    ap.add_argument("--powerlog-phase", default="recruit",
                    choices=("recruit", "combat", "any"))
    ap.add_argument("--powerlog-stride", type=int, default=2000)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--extract", action="store_true", help="强制重新解包")
    args = ap.parse_args(argv)

    if args.extract:
        pkg = ensure_extracted(force=True)
        print(f"[extract] {pkg}")
        return 0
    if args.self_test:
        return _self_test()
    if args.attach_test:
        diag = attach_diagnostics(args.pid)
        print(json.dumps(diag, ensure_ascii=False, indent=1))
        if args.sample:
            _write_json(args.sample, {"schema": SCHEMA, "attach": diag})
        return 0
    if args.from_powerlog:
        path = None if args.from_powerlog == "auto" else Path(args.from_powerlog)
        state = read_state_from_powerlog(path, want_phase=args.powerlog_phase,
                                         stride=args.powerlog_stride,
                                         include_state=args.include_raw)
        if args.sample:
            _write_json(args.sample, state)
            print(f"[sample] written {args.sample}")
        print(json.dumps(state, ensure_ascii=False, indent=1))
        return 0 if state.get("phase") not in ("no_powerlog_frame", "unavailable") else 1
    if args.watch:
        return watch(args.pid, args.interval, args.out, args.jsonl,
                     args.max_seconds, args.hotkey, args.include_raw)
    state = read_live_state(args.pid, include_state=args.include_raw)
    if args.sample:
        _write_json(args.sample, state)
        print(f"[sample] written {args.sample}")
    print(json.dumps(state, ensure_ascii=False, indent=1))
    return 0 if state.get("attached") else 2


if __name__ == "__main__":
    sys.exit(main())
