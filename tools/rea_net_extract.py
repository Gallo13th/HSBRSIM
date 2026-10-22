#!/usr/bin/env python
"""rea_net_extract.py — 从官方客户端 .NET 程序集导出类型/方法/枚举清单。

可复现的「官方实现」静态提取管线（只读游戏目录，产物写 `reversed/`）：

  A. 构建并运行 `reversed/net_extractor`（C# + Mono.Cecil；Mono.Cecil 直接引用
     本机 BepInEx 自带的 DLL，不写游戏目录、不装 NuGet 包）
     → reversed/net/<assembly>/{types.tsv, methods.tsv, enums.json, strings.tsv, refs.json}
  B. 若 `ilspycmd` 可用（`dotnet tool install -g ilspycmd`），额外导出
     Assembly-CSharp 的全量类型清单 → reversed/net_lists/*.txt
  C. 抽取关键枚举到 reversed/net/key_enums.json（供 tools/rea_tag_compare.py）
  D. 生成 reversed/net/SUMMARY.md：BG/战斗相关类型与方法的静态盘点、
     数据加载路径证据、社区程序集（HDT: HearthDb/BobsBuddy）清单

用法:
    python tools/rea_net_extract.py
    python tools/rea_net_extract.py --assemblies Assembly-CSharp
    python tools/rea_net_extract.py --game-dir "C:\\Program Files (x86)\\Hearthstone"
    python tools/rea_net_extract.py --no-ilspy --no-community

退出码: 0 成功；2 环境/程序集缺失；3 提取失败。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVERSED = ROOT / "reversed"
PROJECT = REVERSED / "net_extractor"
BIN = PROJECT / "bin" / "Release" / "net9.0" / "NetExtract.dll"
GAME_DIR = Path(r"C:\Program Files (x86)\Hearthstone")
MANAGED = GAME_DIR / "Hearthstone_Data" / "Managed"

DEFAULT_ASSEMBLIES = ["Assembly-CSharp", "blizzard.bgssdk", "blizzard.bgsclient"]
COMMUNITY_ASSEMBLIES = ["HearthDb", "BobsBuddy", "HearthWatcher"]

#: 关键枚举（官方名 → 输出键）
KEY_ENUMS = {
    "GAME_TAG": "game_tag",
    "TAG_CARDTYPE": "card_type",
    "TAG_ZONE": "zone",
    "TAG_RACE": "race",
    "TAG_SPELL_SCHOOL": "spell_school",
    "TAG_PLAYSTATE": "play_state",
    "TAG_STEP": "step",
    "TAG_PREMIUM": "premium",
    "TAG_RARITY": "rarity",
    "TAG_CARD_SET": "card_set",
}

SURVEY_PATTERNS = [
    ("battlegrounds", r"Battleground|Bacon|TB_Bacon"),
    ("combat", r"Combat|combat"),
    ("simulation", r"Simulat|simulat"),
    ("prediction", r"Predict|predict"),
    ("game_state", r"^GameState$|/GameState|PowerTaskList|PowerProcessor"),
    ("data_loading", r"GameDbf|EntityDef$|CardDbf|CardTagDbf|DbfAsset|DbfRecord"),
]


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 1800,
        env: dict | None = None) -> subprocess.CompletedProcess:
    print(f"[rea] $ {' '.join(str(c) for c in cmd)}")
    e = dict(os.environ)
    e.setdefault("DOTNET_ROLL_FORWARD", "Major")
    if env:
        e.update(env)
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=timeout,
                          env=e)


def find_ilspycmd() -> str | None:
    exe = shutil.which("ilspycmd")
    if exe:
        return exe
    cand = Path(os.environ.get("USERPROFILE", "")) / ".dotnet" / "tools" / "ilspycmd.exe"
    return str(cand) if cand.exists() else None


def find_hdt_dir() -> Path | None:
    """定位 Hearthstone Deck Tracker 的 app-* 目录（社区程序集来源）。"""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "HearthstoneDeckTracker"
    if not base.exists():
        return None
    apps = sorted([p for p in base.glob("app-*") if p.is_dir()])
    return apps[-1] if apps else None


def build_net_extractor() -> bool:
    if BIN.exists() and BIN.stat().st_mtime > (
            PROJECT / "Program.cs").stat().st_mtime:
        print(f"[rea] NetExtract 已构建: {BIN}")
        return True
    cp = run(["dotnet", "build", "-c", "Release", "-v", "q"], cwd=PROJECT,
             timeout=600)
    if cp.returncode != 0:
        print(cp.stdout[-3000:], file=sys.stderr)
        print(cp.stderr[-3000:], file=sys.stderr)
        return False
    return BIN.exists()


def extract(assembly: Path, out_dir: Path, keyword: str | None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["dotnet", str(BIN), str(assembly), str(out_dir)]
    if keyword:
        cmd.append(keyword)
    cp = run(cmd, timeout=1800)
    if cp.returncode != 0:
        print(cp.stdout[-2000:], file=sys.stderr)
        print(cp.stderr[-2000:], file=sys.stderr)
        return {"assembly": assembly.name, "ok": False,
                "stderr": cp.stderr[-2000:]}
    refs = json.loads((out_dir / "refs.json").read_text(encoding="utf-8"))
    refs["ok"] = True
    refs["source"] = str(assembly)
    return refs


def list_types_with_ilspy(ilspy: str, assembly: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    kinds = {"c": "class", "i": "interface", "s": "struct",
             "d": "delegate", "e": "enum"}
    result = {}
    for k, label in kinds.items():
        cp = run([ilspy, "-l", k, str(assembly)], timeout=900)
        if cp.returncode != 0:
            result[label] = None
            continue
        path = out_dir / f"{assembly.stem}.{k}.txt"
        path.write_text(cp.stdout, encoding="utf-8")
        result[label] = len([l for l in cp.stdout.splitlines() if l.strip()])
    return result


def load_enums(asm_out: Path) -> dict:
    p = asm_out / "enums.json"
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}


def read_tsv(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [ln.split("\t") for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def survey(asm_out: Path) -> dict:
    types = read_tsv(asm_out / "types.tsv")
    methods = read_tsv(asm_out / "methods.tsv")
    strings = read_tsv(asm_out / "strings.tsv")
    type_names = [t[1] if len(t) > 1 else "" for t in types]
    method_sigs = [m[0] for m in methods if len(m) > 0]
    out: dict = {"types": len(type_names), "methods": len(method_sigs)}
    for label, pat in SURVEY_PATTERNS:
        rx = re.compile(pat)
        out[label] = {
            "type_count": sum(1 for t in type_names if rx.search(t)),
            "method_count": sum(1 for m in method_sigs if rx.search(m)),
            "type_sample": [t for t in type_names if rx.search(t)][:15],
        }
    sim_methods = [m for m in method_sigs
                   if re.search(r"::(Simulate|RunCombat|StartCombat|"
                                r"ResolveCombat|PredictCombat)", m)]
    out["combat_simulation_methods"] = sim_methods[:40]
    data_rx = re.compile(r"DBF-Asset|Loading DBF|LoadDataFromCardXml|"
                         r"DBF record|DBFS with format|GetDBF|CardXml|"
                         r"cardxml")
    out["data_strings"] = [s for s in strings
                           if len(s) > 1 and data_rx.search(s[1])
                           and ".prefab:" not in s[1]][:40]
    return out


def render_summary(meta: dict, extracted: dict, surveys: dict,
                   key_enums: dict, hdt: Path | None, ilspy: str | None) -> str:
    L: list[str] = []
    L.append("# 官方客户端程序集静态提取摘要（Assembly-CSharp / bgs SDK）\n")
    L.append("> 自动生成，勿手改。复现：`python tools/rea_net_extract.py`\n")
    L.append(f"- 生成时间: {meta['generated_at']}")
    L.append(f"- 游戏目录（只读）: `{GAME_DIR}`")
    L.append("- 反编译/提取工具: Mono.Cecil（本机 BepInEx 自带 DLL）+ "
             f"ilspycmd（{ilspy or '未安装，仅 Cecil 元数据'}）")
    L.append("")
    L.append("## 1. 程序集清单\n")
    L.append("| 程序集 | 类型 | 方法 | 枚举 | 说明 |")
    L.append("|--------|------|------|------|------|")
    desc = {
        "Assembly-CSharp": "官方游戏主程序集（全部游戏逻辑/UI/网络）",
        "blizzard.bgssdk": "Battle.net Game Service SDK（协议/匹配/社交，**非战斗**）",
        "blizzard.bgsclient": "BGS 客户端集成层（Pegasus* 协议消息，**非战斗**）",
        "HearthDb": "社区包（HDT 自带）：官方 DBF 转成的卡牌数据库 + 枚举",
        "BobsBuddy": "社区包（HDT 插件）：**离线酒馆战棋战斗模拟器**（非官方）",
        "HearthWatcher": "社区包（HDT 插件）：Power.log 解析/对局事件（非官方）",
    }
    for name, info in extracted.items():
        L.append(f"| `{name}` | {info.get('types')} | {info.get('methods')} | "
                 f"{info.get('enums')} | {desc.get(name, '')} |")
    L.append("")
    if hdt:
        L.append(f"- 社区程序集来源（只读）: `{hdt}`")
    L.append("")
    ac = surveys.get("Assembly-CSharp")
    if ac:
        L.append("## 2. 酒馆战棋 / 战斗相关类型盘点（Assembly-CSharp）\n")
        L.append("| 关键词 | 类型数 | 方法数 | 类型样例 |")
        L.append("|--------|--------|--------|----------|")
        for label, _pat in SURVEY_PATTERNS:
            s = ac.get(label, {})
            sample = ", ".join(f"`{x}`" for x in (s.get("type_sample") or [])[:6])
            L.append(f"| {label} | {s.get('type_count')} | "
                     f"{s.get('method_count')} | {sample} |")
        L.append("")
        L.append("### 2.1 `Simulate*` / `*Combat` 方法（判断是否存在官方战斗模拟）\n")
        sims = ac.get("combat_simulation_methods") or []
        if sims:
            L.append("```")
            for m in sims:
                L.append(m)
            L.append("```")
        else:
            L.append("无 `Simulate` 类战斗方法。")
        L.append("")
        L.append("### 2.2 数据加载路径证据（GameDbf / EntityDef / CardDbf）\n")
        ds = ac.get("data_strings") or []
        if ds:
            L.append("```")
            for s in ds[:30]:
                L.append(s[0] + "  =>  " + s[1])
            L.append("```")
        L.append("")
    bgs = surveys.get("blizzard.bgssdk")
    if bgs:
        L.append("## 3. bgs SDK 命名空间（Battle.net Game Service）\n")
        L.append(f"- 类型 {bgs.get('types')} / 方法 {bgs.get('methods')} / "
                 f"枚举 {extracted.get('blizzard.bgssdk', {}).get('enums')}")
        L.append("- 典型命名空间: `Blizzard.GameService.Protocol.*`"
                 "（Account/Club/Matchmaking/Channel/Friends/Session）")
        L.append("- 结论：它是战网客户端服务协议，**不含**炉石战棋战斗逻辑。")
        L.append("")
    L.append("## 4. 关键枚举（已导出）\n")
    for key in ("game_tag", "card_type", "zone", "race", "spell_school"):
        e = key_enums.get(key)
        if e:
            L.append(f"- `{key}`（{e.get('official_name')}）: "
                     f"{len(e.get('values') or {})} 个成员")
    L.append("")
    L.append("## 5. 结论\n")
    L.append("- 官方客户端**没有**可离线调用的酒馆战棋战斗模拟器："
             "战斗由服务器 `PowerTaskList` 驱动，客户端只播放/预测 UI 区域。")
    L.append("- 官方**卡牌数据**来自 `GameDbf`（`Data/Win/dbf.unity3d` 资源包）；"
             "`EntityDef.LoadTagFromDBF` 是构造实体的唯一入口。")
    L.append("- 本机 HDT 自带的 `BobsBuddy.dll` 是社区逆向的离线战斗模拟器，"
             "可作为差分测试的参考实现（非官方、非权威）。")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    global GAME_DIR, MANAGED
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game-dir", default=str(GAME_DIR))
    ap.add_argument("--assemblies", action="append", default=None,
                    help=f"要提取的程序集名（默认 {DEFAULT_ASSEMBLIES}）")
    ap.add_argument("--out", default=str(REVERSED / "net"))
    ap.add_argument("--net-lists", default=str(REVERSED / "net_lists"))
    ap.add_argument("--no-ilspy", action="store_true")
    ap.add_argument("--no-community", action="store_true",
                    help="不提取 HDT 自带的 HearthDb/BobsBuddy")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args(argv)

    GAME_DIR = Path(args.game_dir)
    MANAGED = GAME_DIR / "Hearthstone_Data" / "Managed"
    if not MANAGED.exists():
        print(f"[rea] 错误: 找不到官方程序集目录 {MANAGED}", file=sys.stderr)
        return 2
    if not args.skip_build and not build_net_extractor():
        print("[rea] 错误: NetExtract 构建失败（需要 dotnet SDK 9+）", file=sys.stderr)
        return 3

    assemblies = args.assemblies or list(DEFAULT_ASSEMBLIES)
    extracted: dict[str, dict] = {}
    out_root = Path(args.out)
    for name in assemblies:
        src = MANAGED / f"{name}.dll"
        if not src.exists():
            print(f"[rea] 跳过（不存在）: {src}")
            continue
        info = extract(src, out_root / name, None)
        extracted[name] = info
        print(f"[rea] {name}: types={info.get('types')} "
              f"methods={info.get('methods')} enums={info.get('enums')}")
        if not info.get("ok"):
            return 3

    hdt = find_hdt_dir() if not args.no_community else None
    if hdt:
        for name in COMMUNITY_ASSEMBLIES:
            src = hdt / f"{name}.dll"
            if not src.exists():
                continue
            info = extract(src, out_root / name, None)
            extracted[name] = info
            print(f"[rea] {name}（社区）: types={info.get('types')} "
                  f"methods={info.get('methods')} enums={info.get('enums')}")

    # ── ilspy 类型清单 ──
    ilspy = None if args.no_ilspy else find_ilspycmd()
    ilspy_lists = {}
    if ilspy:
        ac_src = MANAGED / "Assembly-CSharp.dll"
        ilspy_lists = list_types_with_ilspy(ilspy, ac_src, Path(args.net_lists))
        print(f"[rea] ilspy 类型清单: {ilspy_lists}")
    else:
        print("[rea] 未找到 ilspycmd（可 dotnet tool install -g ilspycmd）；"
              "仅使用 Mono.Cecil 元数据。")

    # ── 关键枚举 ──
    ac_enums = load_enums(out_root / "Assembly-CSharp")
    key_enums = {}
    for official, key in KEY_ENUMS.items():
        for full, e in ac_enums.items():
            if e.get("name") == official:
                key_enums[key] = {"official_name": official,
                                  "full_name": full,
                                  "values": e["values"]}
                break
    (out_root / "key_enums.json").write_text(
        json.dumps(key_enums, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    # ── 调查/摘要 ──
    surveys = {name: survey(out_root / name) for name in extracted
               if name in ("Assembly-CSharp", "blizzard.bgssdk",
                           "blizzard.bgsclient")}
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "game_dir": str(GAME_DIR),
        "assemblies": {k: {kk: vv for kk, vv in v.items()
                          if kk in ("types", "methods", "enums",
                                    "keyword_strings", "full_name", "source")}
                       for k, v in extracted.items()},
        "ilspy": ilspy,
        "ilspy_lists": ilspy_lists,
        "hdt_dir": str(hdt) if hdt else None,
    }
    (out_root / "SUMMARY.json").write_text(
        json.dumps({**meta, "surveys": surveys,
                    "key_enums": {k: len(v["values"])
                                  for k, v in key_enums.items()}},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_root / "SUMMARY.md").write_text(
        render_summary(meta, extracted, surveys, key_enums, hdt, ilspy) + "\n",
        encoding="utf-8")
    print(f"[rea] 摘要: {out_root / 'SUMMARY.md'}")
    print(f"[rea] 关键枚举: {out_root / 'key_enums.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
