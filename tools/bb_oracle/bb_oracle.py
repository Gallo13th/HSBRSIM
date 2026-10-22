#!/usr/bin/env python3
"""BobsBuddy offline oracle — 本地第三方战斗模拟器调用层。

输入：JSON 战团状态（双方 minion 列表 + 可选 turn/tier/health）。
输出：n 次模拟的 win/tie/loss 概率、平均伤害、仿真次数、耗时。

实现路径（2026-10-18 可行性验证）：
  - BobsBuddy.dll / HearthDb.dll / BobsBuddy.Common.dll 来自 HDT 安装目录；
  - pythonnet 直接加载 .NET assembly（无需 HDT GameV2/实体数据库）；
  - HearthDb.Cards.LoadBaseData() 初始化静态卡库；
  - Simulator.MinionFactory.Create(card_id, controlled) 创建卡脚本子类，
    再手工覆盖 baseAttack/baseHealth/keywords/script data；
  - SimulationRunner.SimulateMultiThreaded(input, iterations, threads, ms)
    返回 Task<Output>（winRate/tieRate/lossRate/avDamage/simulationCount）。

注意：BB 的输入状态空间与 HDT 日志并不完全同构；本工具只映射它能
接受且语义明确的字段，未支持的字段写入 `ignored_fields`，不要默认
"oracle 等于真实状态"。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DLL_DIR = (
    r"%USERPROFILE%\AppData\Local\HearthstoneDeckTracker"
    r"\app-1.59.3"
)
DLLS = ("HearthDb.dll", "BobsBuddy.Common.dll", "BobsBuddy.dll")

_KEYWORD_MAP = {
    "taunt": "taunt",
    "divine_shield": "div",
    "windfury": "windfury",
    "mega_windfury": "megaWindfury",
    "cleave": "cleave",
    "poisonous": "poisonous",
    "venomous": "venomous",
    "reborn": "reborn",
    "stealth": "stealth",
    "cannot_attack": "cannotAttack",
}
_IGNORED_MINION_FIELDS = {
    "enchantments", "attached_to", "attached_modular",
    "additional_deathrattles", "additional_rallies", "races",
}


class OracleError(RuntimeError):
    pass


_clr_ready = False
_bb = None
_HearthDb = None


def _load_bb(dll_dir: str):
    """加载 HDT 的 BobsBuddy 三件套（幂等）。"""
    global _clr_ready, _bb, _HearthDb
    if _clr_ready:
        return _bb, _HearthDb
    try:
        import clr  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise OracleError(
            "pythonnet 不可用；安装：python -m pip install pythonnet"
        ) from exc
    missing = [n for n in DLLS if not (Path(dll_dir) / n).exists()]
    if missing:
        raise OracleError(f"缺少 DLL: {missing}（目录 {dll_dir}）")
    if dll_dir not in sys.path:
        sys.path.insert(0, dll_dir)
    for name in DLLS:
        clr.AddReference(str(Path(dll_dir) / name))
    import HearthDb  # type: ignore
    HearthDb.Cards.LoadBaseData()
    from BobsBuddy.Simulation import (  # type: ignore
        Input, Player, Simulator, SimulationRunner,
    )
    from BobsBuddy import Minion  # type: ignore
    from System.Collections.Generic import List  # type: ignore
    _bb = {
        "Input": Input, "Player": Player, "Simulator": Simulator,
        "SimulationRunner": SimulationRunner, "Minion": Minion, "List": List,
    }
    _HearthDb = HearthDb
    _clr_ready = True
    return _bb, _HearthDb


def _new_list(bb, items=()):
    lst = bb["List"][bb["Minion"]]()
    for item in items:
        lst.Add(item)
    return lst


def _build_minion(bb, sim, spec: Dict[str, Any], controlled: bool,
                  ignored: List[str]) -> Any:
    if not spec.get("card_id"):
        raise OracleError("minion 缺少 card_id")
    try:
        m = sim.MinionFactory.Create(str(spec["card_id"]), controlled)
    except Exception as exc:  # noqa: BLE001
        raise OracleError(
            f"BB 无法创建卡 {spec.get('card_id')}: {exc}"
        ) from exc
    if m is None:
        raise OracleError(f"BB 返回空 minion: {spec.get('card_id')}")
    # 基础属性：BB 的卡脚本子类默认值为 0；用战斗边界快照值覆盖。
    if spec.get("atk") is not None:
        m.baseAttack = int(spec["atk"])
    if spec.get("health") is not None:
        m.baseHealth = int(spec["health"])
    if spec.get("golden"):
        try:
            m.golden = True
        except Exception:  # noqa: BLE001
            pass
    if spec.get("tier") is not None:
        try:
            m.tier = int(spec["tier"])
        except Exception:  # noqa: BLE001
            pass
    if spec.get("is_deity"):
        # BB 的 Deity 实体（隐藏状态，需显式标记）
        try:
            m.IsDeity = True
        except Exception:  # noqa: BLE001
            ignored.append("minion.is_deity")
    for kw in spec.get("keywords") or []:
        key = str(kw).strip().lower().replace("-", "_").replace(" ", "_")
        attr = _KEYWORD_MAP.get(key)
        if attr is None:
            ignored.append(f"keyword:{kw}")
            continue
        try:
            if attr == "div":
                m.div = 1
            else:
                setattr(m, attr, True)
        except Exception:  # noqa: BLE001
            ignored.append(f"keyword:{kw}")
    for raw_num, value in (spec.get("script_data") or {}).items():
        try:
            num = int(str(raw_num).replace("script_data_num_", "")
                      .replace("ScriptDataNum", "")
                      .replace("script_data_num", "")
                      .replace("num_", "").replace("NUM_", ""))
            if not 1 <= num <= 4:
                ignored.append(f"script_data:{raw_num}")
                continue
            setattr(m, f"ScriptDataNum{num}", int(value))
        except Exception:  # noqa: BLE001
            ignored.append(f"script_data:{raw_num}")
    for key in spec:
        if key in _IGNORED_MINION_FIELDS and spec.get(key):
            ignored.append(f"minion.{key}")
    if spec.get("trace_extra_tags"):
        ignored.append("trace_tags:"
                       + ",".join(sorted(spec["trace_extra_tags"])))
    return m


def _build_input(bb, payload: Dict[str, Any]) -> tuple:
    ignored: List[str] = []
    sim = bb["Simulator"]()
    inp = bb["Input"]()
    p = bb["Player"](inp)
    o = bb["Player"](inp)
    for side_name, player, band in (("player", p, payload.get("player") or {}),
                                    ("opponent", o,
                                     payload.get("opponent") or {})):
        minions = []
        for spec in band.get("minions") or []:
            minions.append(_build_minion(
                bb, sim, spec, side_name == "player", ignored))
        player.Side = _new_list(bb, minions)
        if band.get("health") is not None:
            player.Health = int(band["health"])
        if band.get("tier") is not None:
            player.Tier = int(band["tier"])
        # 可选英雄技能（卡 id 列表）；BB 的 HeroPowerData 需要 id/data，
        # 这里只喂 id + 默认 0，真实 data 需由调用方扩展 schema。
        for power in band.get("hero_powers") or []:
            try:
                pid = str(power.get("card_id") if isinstance(power, dict)
                          else power)
                data = (power.get("data") if isinstance(power, dict)
                        else 0) or 0
                player.AddHeroPower(pid, side_name == "player", False,
                                    int(data), 0, 0, None, 0)
            except Exception:  # noqa: BLE001
                ignored.append(f"hero_power:{power}")
        if band.get("friendly_deity_sigil"):
            sigil = band["friendly_deity_sigil"]
            applied = False
            try:
                if isinstance(sigil, dict):
                    sigil_minion = _build_minion(
                        bb, sim, sigil, side_name == "player", ignored)
                    player.FriendlyDeitySigil = sigil_minion
                else:
                    # 优先按 card id（bridge 联调确认 BB 接受）；
                    # 不兼容时退回构造 Minion 实体。
                    try:
                        player.FriendlyDeitySigil = str(sigil)
                    except Exception:  # noqa: BLE001
                        sigil_minion = sim.MinionFactory.Create(
                            str(sigil), side_name == "player")
                        player.FriendlyDeitySigil = sigil_minion
                applied = True
            except Exception:  # noqa: BLE001
                applied = False
            if not applied:
                ignored.append("friendly_deity_sigil")
        if band.get("trinkets"):
            ignored.append("trinkets(unsupported)")
        if band.get("quests"):
            ignored.append("quests(unsupported)")
    inp.Player = p
    inp.Opponent = o
    if payload.get("turn") is not None:
        inp.SetTurn(int(payload["turn"]))
    if payload.get("available_races"):
        # Race enum 映射未实现；不伪造成空列表，只记录 unsupported。
        ignored.append("available_races")
    return sim, inp, ignored


def run_oracle(payload: Dict[str, Any], *, dll_dir: Optional[str] = None,
               iterations: Optional[int] = None,
               threads: Optional[int] = None,
               time_limit_ms: Optional[int] = None) -> Dict[str, Any]:
    """运行 BB oracle；返回 JSON 可序列化结果。"""
    started = time.perf_counter()
    bb, _ = _load_bb(dll_dir or os.environ.get(
        "BOBSBUDDY_DLL_DIR", DEFAULT_DLL_DIR))
    sim, inp, ignored = _build_input(bb, payload)
    iters = int(iterations if iterations is not None
                else payload.get("iterations", 1000))
    th = int(threads if threads is not None
             else payload.get("threads", 1))
    limit = int(time_limit_ms if time_limit_ms is not None
                else payload.get("time_limit_ms", 20000))
    try:
        task = bb["SimulationRunner"]().SimulateMultiThreaded(
            inp, iters, th, limit)
        out = task.GetAwaiter().GetResult()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "ignored_fields": ignored,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
    result = {
        "ok": True,
        "win": float(out.winRate),
        "tie": float(out.tieRate),
        "loss": float(out.lossRate),
        "av_damage": float(out.avDamage),
        "median_damage": float(out.medianDamage),
        "simulation_count": int(out.simulationCount),
        "friendly_health": int(out.friendlyHealth),
        "opponent_health": int(out.opponentHealth),
        "ignored_fields": sorted(set(ignored)),
        "elapsed_s": round(time.perf_counter() - started, 3),
        "sec_per_1000": None,
    }
    if result["simulation_count"]:
        result["sec_per_1000"] = round(
            result["elapsed_s"] * 1000.0 / result["simulation_count"], 4)
    return result


def trace_to_payload(trace: Dict[str, Any], *,
                     iterations: int = 1000,
                     threads: int = 1,
                     time_limit_ms: int = 20000) -> Dict[str, Any]:
    """把 official_combat_trace.v1 JSON 转成 oracle 输入（尽力映射）。"""
    def side(band):
        minions = []
        for m in (band.get("minions") or []):
            tags = m.get("tags") or {}
            script_data = {}
            ignored_tags = []
            for key, value in tags.items():
                if str(key).startswith("ScriptDataNum"):
                    script_data[str(key)] = value
                else:
                    ignored_tags.append(str(key))
            minions.append({
                "card_id": m.get("card_id"),
                "atk": m.get("atk"),
                "health": m.get("health"),
                "golden": bool(m.get("golden")),
                "keywords": list(m.get("keywords") or []),
                "script_data": script_data,
                "tier": m.get("tier"),
                # 不要把 tags 直接塞进 ignored_fields（会爆量）；只标存在
                "trace_extra_tags": ignored_tags,
            })
        return {
            "tier": band.get("tier"),
            "health": band.get("health", 30),
            "minions": minions,
        }
    return {
        "turn": trace.get("turn"),
        "iterations": iterations,
        "threads": threads,
        "time_limit_ms": time_limit_ms,
        "player": side(trace.get("player") or {}),
        "opponent": side(trace.get("opponent") or {}),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="BobsBuddy offline oracle")
    ap.add_argument("--input", type=Path, help="JSON 输入文件")
    ap.add_argument("--trace", type=Path,
                    help="official_combat_trace.v1 JSON（与 --input 二选一）")
    ap.add_argument("--out", type=Path, help="输出 JSON 路径（默认 stdout）")
    ap.add_argument("--iterations", type=int, default=None)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--time-limit-ms", type=int, default=None)
    ap.add_argument("--dll-dir", default=None)
    args = ap.parse_args(argv)
    if bool(args.input) == bool(args.trace):
        ap.error("必须且只能给 --input 或 --trace 之一")
    if args.trace:
        trace = json.loads(args.trace.read_text(encoding="utf-8"))
        payload = trace_to_payload(
            trace,
            iterations=args.iterations or 1000,
            threads=args.threads or 1,
            time_limit_ms=args.time_limit_ms or 20000,
        )
    else:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = run_oracle(
        payload, dll_dir=args.dll_dir,
        iterations=args.iterations, threads=args.threads,
        time_limit_ms=args.time_limit_ms,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
